#!/usr/bin/env python3
"""
Unit Tests for AuthService:
- Argon2id Hashing & Verification
- Legacy PBKDF2 Verification & Auto-Upgrade
- Password Policy Validation
- Session Lifecycle & Revocation
- Reset Token Hashing & Invalidation
- Rate Limiter Sliding Window
- Safe User Profile Sanitization
"""

import os
import sys
import uuid
import pytest

# Ensure backend root is on path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from services.auth_service import AuthService
from core.redis_store import RedisStore


class TestAuthServiceUnit:
    @classmethod
    def setup_class(cls):
        cls.store = RedisStore()
        cls.auth = AuthService(store=cls.store)

    def test_argon2id_hashing_and_verification(self):
        password = "GodLevelPassword999!"
        hashed = self.auth.hash_password(password)

        assert hashed.startswith("$argon2id$"), f"Expected Argon2id prefix, got {hashed}"
        assert self.auth.verify_password(password, hashed) is True
        assert self.auth.verify_password("WrongPassword123!", hashed) is False
        assert self.auth.verify_password("", hashed) is False

    def test_legacy_pbkdf2_fallback_verification(self):
        # Emulate a legacy PBKDF2 hash
        import hashlib, secrets
        salt = secrets.token_bytes(16)
        pwd = "LegacySecretPassword123!"
        pwd_hash = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt, 600_000)
        legacy_hash = f"pbkdf2_sha256$600000${salt.hex()}${pwd_hash.hex()}"

        assert self.auth.verify_password(pwd, legacy_hash) is True
        assert self.auth.verify_password("WrongPassword!", legacy_hash) is False

    def test_password_policy_validation(self):
        # Short password (< 8 chars)
        ok, msg = self.auth.validate_password("Short1!")
        assert ok is False
        assert "8 characters" in msg

        # No numbers/symbols
        ok, msg = self.auth.validate_password("NoNumbersOnlyLetters")
        assert ok is False
        assert "number or special character" in msg

        # Valid strong password
        ok, msg = self.auth.validate_password("CorrectHorseBattery99!")
        assert ok is True
        assert msg == ""

    def test_email_validation(self):
        assert self.auth.validate_email("user@example.com") is True
        assert self.auth.validate_email("first.last+tag@sub.domain.org") is True
        assert self.auth.validate_email("invalid-email") is False
        assert self.auth.validate_email("@missinguser.com") is False
        assert self.auth.validate_email("") is False

    def test_session_lifecycle_and_revocation(self):
        email = f"session_{uuid.uuid4().hex[:8]}@example.com"
        user, _, error = self.auth.signup(email, "SessionPassword123!")
        assert error == ""
        user_id = user["id"]
        token, session = self.auth.create_session(user_id, user_agent="Mozilla/5.0 Test", ip_address="127.0.0.1")

        assert token is not None
        assert session["user_id"] == user_id
        assert session["status"] == "active"
        assert "created_at" in session
        assert "expires_at" in session

        # Fetch session
        fetched = self.auth.get_session(token)
        assert fetched is not None
        assert fetched["user_id"] == user_id

        # Revoke session
        self.auth.logout(token)
        revoked = self.auth.get_session(token)
        assert revoked is None

    def test_reset_token_hashing_and_one_time_use(self):
        email = f"reset_test_{uuid.uuid4().hex[:8]}@example.com"
        user, _, _ = self.auth.signup(email, "InitialPassword123!", name="Reset Tester")
        assert user is not None
        user_id = user["id"]

        # Generate reset token
        raw_token, msg = self.auth.create_reset_token(email)
        assert raw_token is not None

        # Verify password cannot be seen/leaked
        safe_user = self.auth.get_user_by_id(user_id)
        assert "password_hash" not in safe_user

        # Reset password
        new_pwd = "NewSecurePassword456!"
        success, reset_msg = self.auth.reset_password(raw_token, new_pwd)
        assert success is True

        # Token cannot be reused (one-time use!)
        reused_success, _ = self.auth.reset_password(raw_token, "AnotherPassword789!")
        assert reused_success is False, "Reset token must be invalidated after first use"

        # Login with new password
        login_user, new_token, err = self.auth.login(email, new_pwd)
        assert login_user is not None
        assert err == ""

    def test_multi_session_revocation_on_password_reset(self):
        email = f"multi_sess_{uuid.uuid4().hex[:8]}@example.com"
        self.auth.signup(email, "InitialPassword123!")
        _, token1, _ = self.auth.login(email, "InitialPassword123!")
        _, token2, _ = self.auth.login(email, "InitialPassword123!")
        _, token3, _ = self.auth.login(email, "InitialPassword123!")

        # All 3 sessions should be active
        assert self.auth.get_session(token1) is not None
        assert self.auth.get_session(token2) is not None
        assert self.auth.get_session(token3) is not None

        # Reset password
        raw_token, _ = self.auth.create_reset_token(email)
        self.auth.reset_password(raw_token, "NewPassword789!")

        # All 3 old sessions must be revoked
        assert self.auth.get_session(token1) is None
        assert self.auth.get_session(token2) is None
        assert self.auth.get_session(token3) is None

    def test_rate_limiter(self):
        test_key = f"test_ip_{uuid.uuid4().hex[:6]}"
        limit = 5
        window = 2

        # First 5 calls allowed
        for _ in range(limit):
            allowed, _ = self.auth.check_rate_limit(test_key, limit=limit, window_seconds=window)
            assert allowed is True

        # 6th call blocked
        allowed, retry_after = self.auth.check_rate_limit(test_key, limit=limit, window_seconds=window)
        assert allowed is False
        assert retry_after > 0


if __name__ == "__main__":
    t = TestAuthServiceUnit()
    t.setup_class()
    t.test_argon2id_hashing_and_verification()
    print("✅ test_argon2id_hashing_and_verification passed")
    t.test_legacy_pbkdf2_fallback_verification()
    print("✅ test_legacy_pbkdf2_fallback_verification passed")
    t.test_password_policy_validation()
    print("✅ test_password_policy_validation passed")
    t.test_email_validation()
    print("✅ test_email_validation passed")
    t.test_session_lifecycle_and_revocation()
    print("✅ test_session_lifecycle_and_revocation passed")
    t.test_reset_token_hashing_and_one_time_use()
    print("✅ test_reset_token_hashing_and_one_time_use passed")
    t.test_multi_session_revocation_on_password_reset()
    print("✅ test_multi_session_revocation_on_password_reset passed")
    t.test_rate_limiter()
    print("✅ test_rate_limiter passed")
    print("\n🏁 ALL AUTH UNIT TESTS PASSED SUCCESSFULLY!")
