import hashlib
import hmac
import logging
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

try:
    import argon2
    from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
    _ARGON2_HASHER = argon2.PasswordHasher(
        time_cost=2,
        memory_cost=65536,
        parallelism=1,
        hash_len=32,
        type=argon2.Type.ID,
    )
    _HAS_ARGON2 = True
except ImportError:
    _ARGON2_HASHER = None
    _HAS_ARGON2 = False
    logger.warning("argon2-cffi not installed; falling back to PBKDF2-HMAC-SHA256")

from core.config import get_settings
from core.redis_store import RedisStore
from core.postgres_store import PostgresStore


class AuthService:
    """Production-grade user authentication, Argon2id security, and session management."""

    def __init__(self, store: RedisStore | None = None):
        self.settings = get_settings()
        self.store = store or RedisStore()
        self.db = PostgresStore() if store is None and get_settings().database_url else None

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using Argon2id (or secure PBKDF2 fallback)."""
        if _HAS_ARGON2 and _ARGON2_HASHER:
            return _ARGON2_HASHER.hash(password)
        salt = secrets.token_bytes(16)
        pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
        return f"pbkdf2_sha256$600000${salt.hex()}${pwd_hash.hex()}"

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        """Verify a plaintext password against a stored hash (Argon2id with PBKDF2 fallback)."""
        if not stored_hash:
            return False

        # 1. Argon2id check
        if stored_hash.startswith("$argon2"):
            try:
                return _ARGON2_HASHER.verify(stored_hash, password)
            except (VerifyMismatchError, VerificationError, InvalidHashError):
                return False
            except Exception as e:
                logger.error("Argon2 verification unexpected error: %s", e)
                return False

        # 2. Legacy PBKDF2-HMAC-SHA256 fallback (to avoid breaking existing users)
        if stored_hash.startswith("pbkdf2_sha256$"):
            try:
                parts = stored_hash.split("$")
                if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
                    _, iterations, salt_hex, hash_hex = parts
                    salt = bytes.fromhex(salt_hex)
                    expected = bytes.fromhex(hash_hex)
                    calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
                    return hmac.compare_digest(calc, expected)
            except Exception as e:
                logger.error("PBKDF2 verification unexpected error: %s", e)
                return False

        # 3. Simple SHA-256 legacy check (if any old dev users exist)
        if len(stored_hash) == 64 and all(c in "0123456789abcdefABCDEF" for c in stored_hash):
            calc = hashlib.sha256(password.encode("utf-8")).hexdigest()
            return hmac.compare_digest(calc, stored_hash.lower())

        return False

    @staticmethod
    def validate_password(password: str) -> tuple[bool, str]:
        """Validate password strength according to SaaS security policy (min 8 chars, at least one number or special char)."""
        if not password or len(password) < 8:
            return False, "Password must be at least 8 characters long."
        if not re.search(r"[\d\W_]", password):
            return False, "Password must contain at least one number or special character."
        return True, ""

    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email format."""
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        return bool(re.match(pattern, email.strip()))

    def check_rate_limit(self, key: str, limit: int = 5, window_seconds: int = 60) -> tuple[bool, int]:
        """Check rate limiting using Redis atomic counter with TTL window."""
        rate_key = f"rate_limit:{key}"
        try:
            current = self.store.client.incr(rate_key)
            if current == 1:
                self.store.client.expire(rate_key, window_seconds)
                return True, 0
            if current > limit:
                ttl = self.store.client.ttl(rate_key)
                return False, max(1, ttl)
            return True, 0
        except Exception as e:
            logger.warning("Rate limit check failed (failing open): %s", e)
            return True, 0

    def create_session(self, user_id: str, user_agent: str = "", ip_address: str = "") -> tuple[str, dict[str, Any]]:
        """Create a cryptographically random session token and save metadata."""
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        ttl = int(getattr(self.settings, "session_ttl_seconds", 7 * 24 * 3600))
        expires = now + timedelta(seconds=ttl)

        session_record = {
            "session_id": str(uuid.uuid4()),
            "user_id": user_id,
            "token": token,
            "csrf_token": csrf_token,
            "user_agent": user_agent,
            "ip_address": ip_address,
            "created_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "last_seen_at": now.isoformat(),
            "status": "active",
        }

        # Store full session record
        self.store.hset_json(f"auth_session:{token}", session_record)
        self.store.client.expire(f"auth_session:{token}", ttl)

        # Fast lookup mapping: session_token -> user_id
        self.store.client.set(f"session_token:{token}", user_id, ex=ttl)

        # Track user's active session tokens for multi-session revocation
        self.store.client.sadd(f"user:{user_id}:auth_sessions", token)

        # Also register in PostgreSQL if DB is available
        if self.db:
            try:
                tenant_id = self.db.user_tenant(user_id) if hasattr(self.db, "user_tenant") else None
                if tenant_id and hasattr(self.db, "create_session"):
                    self.db.create_session(user_id=user_id, tenant_id=tenant_id, user_agent=user_agent, ip_address=ip_address, ttl=ttl)
            except Exception as e:
                logger.warning("Could not persist auth session to postgres: %s", e)

        return token, session_record

    def get_session(self, token: str) -> dict[str, Any] | None:
        """Retrieve and validate session record from Redis."""
        if not token:
            return None

        # Try primary auth_session key
        session_data = self.store.hgetall_json(f"auth_session:{token}")
        if session_data and session_data.get("status") == "active":
            now_iso = datetime.now(timezone.utc).isoformat()
            session_data["last_seen_at"] = now_iso
            return session_data

        # Fallback to legacy session_token key
        uid_raw = self.store.client.get(f"session_token:{token}")
        if uid_raw:
            uid = uid_raw.decode("utf-8") if isinstance(uid_raw, bytes) else str(uid_raw)
            return {
                "session_id": "legacy",
                "user_id": uid,
                "token": token,
                "status": "active",
            }

        return None

    def get_user_by_token(self, token: str) -> dict[str, Any] | None:
        """Get safe user profile by session token."""
        session = self.get_session(token)
        if not session:
            return None
        user_id = session.get("user_id")
        if not user_id:
            return None
        return self.get_user_by_id(user_id)

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        """Get sanitized user object by user_id (never returns password_hash)."""
        if not user_id:
            return None

        user_data = self.store.hgetall_json(f"user:{user_id}")
        if user_data:
            return {k: v for k, v in user_data.items() if k != "password_hash"}

        # Fallback to PostgreSQL
        if self.db:
            db_user = self.db.get_user_by_id(user_id)
            if db_user:
                self.store.hset_json(f"user:{user_id}", db_user)
                if db_user.get("email"):
                    self.store.client.set(f"user_email_index:{db_user['email'].lower()}", user_id)
                return {k: v for k, v in db_user.items() if k != "password_hash"}

        return None

    def signup(self, email: str, password: str, name: str | None = None, user_agent: str = "", ip_address: str = "") -> tuple[dict[str, Any] | None, str | None, str]:
        """Register a new user account with Argon2id hashing and create an active session."""
        clean_email = email.strip().lower()
        if not self.validate_email(clean_email):
            return None, None, "Invalid email address format."

        valid_pwd, err_msg = self.validate_password(password)
        if not valid_pwd:
            return None, None, err_msg

        # Check for existing email in PostgreSQL and Redis
        if self.db and self.db.get_user_by_email(clean_email):
            return None, None, "An account with this email already exists."

        existing_uid = self.store.client.get(f"user_email_index:{clean_email}")
        if existing_uid:
            return None, None, "An account with this email already exists."

        hashed = self.hash_password(password)
        now = datetime.now(timezone.utc).isoformat()
        display_name = (name or "").strip() or clean_email.split("@")[0].capitalize()

        # Authoritative persistence in PostgreSQL
        tenant_id = None
        if self.db:
            try:
                db_user = self.db.create_user(clean_email, hashed, display_name)
                user_id = str(db_user["id"])
                tenant_id = str(db_user.get("tenant_id", "")) if db_user.get("tenant_id") else None
            except ValueError:
                return None, None, "An account with this email already exists."
        else:
            user_id = str(uuid.uuid4())

        user_data = {
            "id": user_id,
            "tenant_id": tenant_id,
            "email": clean_email,
            "name": display_name,
            "password_hash": hashed,
            "created_at": now,
            "updated_at": now,
        }

        # Cache in Redis for performance
        self.store.hset_json(f"user:{user_id}", user_data)
        self.store.client.set(f"user_email_index:{clean_email}", user_id)
        self.store.client.sadd("users:all", user_id)

        # Do NOT create an authenticated session on signup — explicit sign-in is required
        safe_user = {k: v for k, v in user_data.items() if k != "password_hash"}
        return safe_user, None, ""

    def login(self, email: str, password: str, user_agent: str = "", ip_address: str = "") -> tuple[dict[str, Any] | None, str | None, str]:
        """Authenticate user credentials against PostgreSQL/Redis and issue a new session token."""
        clean_email = email.strip().lower()

        # 1. Authoritative lookup from PostgreSQL if available
        user_data = None
        stored_hash = ""
        user_id = None

        if self.db:
            db_user = getattr(self.db, "get_user_credentials_by_email", self.db.get_user_by_email)(clean_email)
            if db_user:
                user_id = str(db_user["id"])
                stored_hash = db_user.get("password_hash", "")
                user_data = {
                    "id": user_id,
                    "email": clean_email,
                    "name": db_user.get("name") or clean_email.split("@")[0].capitalize(),
                    "password_hash": stored_hash,
                    "created_at": str(db_user.get("created_at", "")),
                    "updated_at": str(db_user.get("updated_at", "")),
                }
                # Sync cache
                self.store.hset_json(f"user:{user_id}", user_data)
                self.store.client.set(f"user_email_index:{clean_email}", user_id)

        # 2. Redis fallback lookup
        if not user_data:
            uid_raw = self.store.client.get(f"user_email_index:{clean_email}")
            if not uid_raw:
                return None, None, "Invalid email or password."
            user_id = uid_raw.decode("utf-8") if isinstance(uid_raw, bytes) else str(uid_raw)
            user_data = self.store.hgetall_json(f"user:{user_id}")
            if not user_data:
                return None, None, "Invalid email or password."
            stored_hash = user_data.get("password_hash", "")

        # 3. Verify password
        if not self.verify_password(password, stored_hash):
            return None, None, "Invalid email or password."

        # Transparent upgrade to Argon2id if user previously had PBKDF2 hash
        if stored_hash.startswith("pbkdf2_sha256$"):
            try:
                new_hash = self.hash_password(password)
                user_data["password_hash"] = new_hash
                user_data["updated_at"] = datetime.now(timezone.utc).isoformat()
                self.store.hset_json(f"user:{user_id}", user_data)
                if self.db:
                    self.db.update_password(user_id, new_hash)
                logger.info("Upgraded user %s password hash to Argon2id", user_id)
            except Exception as e:
                logger.warning("Could not auto-upgrade password hash: %s", e)

        token, _ = self.create_session(user_id, user_agent=user_agent, ip_address=ip_address)
        safe_user = {k: v for k, v in user_data.items() if k != "password_hash"}
        return safe_user, token, ""

    def logout(self, token: str) -> bool:
        """Alias for revoke_session."""
        return self.revoke_session(token)

    def revoke_session(self, token: str) -> bool:
        """Revoke a single session token."""
        if not token:
            return False
        session = self.get_session(token)
        user_id = session.get("user_id") if session else None

        if user_id:
            self.store.client.srem(f"user:{user_id}:auth_sessions", token)

        self.store.client.delete(f"auth_session:{token}")
        self.store.client.delete(f"session_token:{token}")
        if self.db:
            try:
                self.db.delete_session(token)
            except Exception as e:
                logger.warning("Could not delete session from postgres: %s", e)
        return True

    def revoke_all_user_sessions(self, user_id: str) -> int:
        """Revoke all active sessions for a user (used after password reset)."""
        raw_tokens = self.store.client.smembers(f"user:{user_id}:auth_sessions")
        count = 0
        for tok in raw_tokens:
            tok_str = tok.decode("utf-8") if isinstance(tok, bytes) else str(tok)
            self.store.client.delete(f"auth_session:{tok_str}")
            self.store.client.delete(f"session_token:{tok_str}")
            count += 1
        self.store.client.delete(f"user:{user_id}:auth_sessions")
        if self.db:
            try:
                self.db.delete_user_sessions(user_id)
            except Exception as e:
                logger.warning("Could not delete user sessions from postgres: %s", e)
        return count

    def create_reset_token(self, email: str) -> tuple[str | None, str]:
        """Generate a one-time SHA-256 hashed password reset token with 1-hour expiry."""
        clean_email = email.strip().lower()
        uid_raw = self.store.client.get(f"user_email_index:{clean_email}")
        user_id = None
        if uid_raw:
            user_id = uid_raw.decode("utf-8") if isinstance(uid_raw, bytes) else str(uid_raw)
        elif self.db:
            db_user = self.db.get_user_by_email(clean_email)
            if db_user:
                user_id = str(db_user["id"])

        if not user_id:
            # Prevent email enumeration by returning uniform success message
            return None, "If an account with that email exists, we've sent a password reset link."

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

        ttl = self.settings.reset_token_ttl_seconds
        # Store SHA-256 hash of token in Redis (never store raw reset token in DB)
        self.store.client.set(f"pwd_reset:{token_hash}", user_id, ex=ttl)

        return raw_token, "If an account with that email exists, we've sent a password reset link."

    def reset_password(self, token: str, new_password: str) -> tuple[bool, str]:
        """Reset password using one-time token, update to Argon2id, and invalidate all active sessions."""
        valid_pwd, err_msg = self.validate_password(new_password)
        if not valid_pwd:
            return False, err_msg

        if not token:
            return False, "That password reset link is invalid or has expired. Please request a new one."

        # Verify hashed token in Redis
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        uid_raw = self.store.client.get(f"pwd_reset:{token_hash}")

        if not uid_raw:
            return False, "That password reset link is invalid or has expired. Please request a new one."

        user_id = uid_raw.decode("utf-8") if isinstance(uid_raw, bytes) else str(uid_raw)
        user_data = self.store.hgetall_json(f"user:{user_id}") or {}

        # Hash new password with Argon2id
        hashed = self.hash_password(new_password)
        user_data["password_hash"] = hashed
        user_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.store.hset_json(f"user:{user_id}", user_data)

        if self.db:
            try:
                self.db.update_password(user_id, hashed)
            except Exception as e:
                logger.warning("Could not update password in postgres: %s", e)

        # Invalidate reset token immediately (one-time use)
        self.store.client.delete(f"pwd_reset:{token_hash}")

        # Invalidate all existing sessions for this user for security
        self.revoke_all_user_sessions(user_id)

        return True, "Password has been successfully updated. You can now log in."

    def change_password(self, user_id: str, current_password: str, new_password: str) -> tuple[bool, str]:
        """Change password for an authenticated user."""
        user_data = self.store.hgetall_json(f"user:{user_id}")
        stored_hash = ""
        if user_data:
            stored_hash = user_data.get("password_hash", "")
        elif self.db:
            db_user = self.db.get_user_by_id(user_id)
            if db_user:
                stored_hash = db_user.get("password_hash", "")

        if not stored_hash:
            return False, "User account not found."

        if not self.verify_password(current_password, stored_hash):
            return False, "Current password is incorrect."

        valid_pwd, err_msg = self.validate_password(new_password)
        if not valid_pwd:
            return False, err_msg

        hashed = self.hash_password(new_password)
        if user_data:
            user_data["password_hash"] = hashed
            user_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.store.hset_json(f"user:{user_id}", user_data)

        if self.db:
            self.db.update_password(user_id, hashed)

        return True, "Password successfully changed."
