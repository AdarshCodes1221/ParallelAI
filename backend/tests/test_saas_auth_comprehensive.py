#!/usr/bin/env python3
"""
Comprehensive 20-Scenario SaaS Authentication and Security Test Suite.
Tests all phases of the SaaS auth flow:
1. Signup success
2. Duplicate signup rejected
3. Login success
4. Wrong password rejected
5. Unknown email login rejected generically
6. Forgot password returns success without revealing account existence
7. Forgot password response DOES NOT contain reset_token
8. Reset token is hashed in storage
9. Reset link has raw token only in email provider layer
10. Reset with valid token works
11. Reset with invalid token fails
12. Reset with expired token fails
13. Reset token cannot be reused
14. Existing sessions become invalid after password reset
15. New password allows login
16. Old password no longer works
17. Logout invalidates session
18. Refresh preserves login while session is valid
19. Rate limiting works
20. Password reset does not reveal whether an email exists
"""

import hashlib
import os
import sys
import time
import uuid
import pytest
from fastapi.testclient import TestClient

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app
from services.auth_service import AuthService
from services.email_provider import EmailProvider
from core.redis_store import RedisStore
from core.config import get_settings


def get_unique_ip():
    return f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"


class TestSaaSAuthComprehensive:
    @classmethod
    def setup_class(cls):
        cls.client = TestClient(app, base_url="http://localhost:8000")
        cls.store = RedisStore()
        cls.auth_service = AuthService(store=cls.store)
        cls.settings = get_settings()

    def test_01_signup_success(self):
        """1. Signup success with valid credentials, no session cookies or tokens, and 401 on /me."""
        email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "SaaSUserPass123!"
        name = "Ada Lovelace"
        ip = get_unique_ip()

        client = TestClient(app, base_url="http://localhost:8000")
        res = client.post(
            "/api/auth/signup",
            json={"email": email, "password": pwd, "name": name},
            headers={"X-Forwarded-For": ip},
        )
        assert res.status_code == 200, f"Signup failed: {res.text}"
        data = res.json()
        assert data["status"] == "ok"
        assert data["message"] == "Account created successfully. Please sign in."
        assert data["user"]["email"] == email
        assert data["user"]["name"] == name
        assert "password_hash" not in data["user"], "Password hash must not be returned!"
        assert "session_token" not in res.cookies, "HttpOnly session_token cookie must NOT be set on signup!"
        assert "session_token" not in client.cookies, "HttpOnly session_token cookie must NOT be set in client on signup!"
        assert "token" not in data, "Session token must NOT be returned in signup response!"

        # Immediately calling /me after signup without login returns 401
        res_me = client.get("/api/auth/me")
        assert res_me.status_code == 401, "Unauthenticated /me after signup must return 401"

    def test_02_duplicate_signup_rejected(self):
        """2. Duplicate signup rejected with clear error."""
        email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "SaaSUserPass123!"
        ip = get_unique_ip()

        res1 = self.client.post("/api/auth/signup", json={"email": email, "password": pwd}, headers={"X-Forwarded-For": ip})
        assert res1.status_code == 200

        res2 = self.client.post("/api/auth/signup", json={"email": email, "password": pwd}, headers={"X-Forwarded-For": ip})
        assert res2.status_code == 400
        assert "already exists" in res2.json()["detail"].lower()

    def test_03_login_success(self):
        """3. Login success with valid password and cookie creation."""
        email = f"login_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "ValidPassword999!"
        ip = get_unique_ip()

        # Create user
        self.client.post("/api/auth/signup", json={"email": email, "password": pwd}, headers={"X-Forwarded-For": ip})

        client = TestClient(app, base_url="http://localhost:8000")
        res = client.post("/api/auth/login", json={"email": email, "password": pwd}, headers={"X-Forwarded-For": ip})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["user"]["email"] == email
        assert "session_token" in client.cookies
        assert "csrf_token" in client.cookies

    def test_04_wrong_password_rejected(self):
        """4. Wrong password rejected with 401."""
        email = f"wrongpwd_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "CorrectPassword123!"
        ip = get_unique_ip()

        self.client.post("/api/auth/signup", json={"email": email, "password": pwd}, headers={"X-Forwarded-For": ip})

        client = TestClient(app, base_url="http://localhost:8000")
        res = client.post("/api/auth/login", json={"email": email, "password": "WrongPassword999!"}, headers={"X-Forwarded-For": ip})
        assert res.status_code == 401
        assert "invalid email or password" in res.json()["detail"].lower()

    def test_05_unknown_email_rejected_generically(self):
        """5. Unknown email login rejected generically without disclosing existence."""
        ip = get_unique_ip()
        client = TestClient(app, base_url="http://localhost:8000")
        res = client.post(
            "/api/auth/login",
            json={"email": f"nonexistent_{uuid.uuid4().hex[:8]}@example.com", "password": "AnyPassword123!"},
            headers={"X-Forwarded-For": ip},
        )
        assert res.status_code == 401
        assert "invalid email or password" in res.json()["detail"].lower()

    def test_06_and_07_forgot_password_no_token_leakage(self, monkeypatch):
        """6 & 7. Forgot password returns success without revealing account existence, and NEVER leaks reset_token."""
        email = f"forgot_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "SecretPass123!"
        ip = get_unique_ip()
        self.client.post("/api/auth/signup", json={"email": email, "password": pwd}, headers={"X-Forwarded-For": ip})

        captured_reset_urls = []

        def mock_send_password_reset(self_provider, recipient, reset_url):
            captured_reset_urls.append((recipient, reset_url))

        monkeypatch.setattr(EmailProvider, "send_password_reset", mock_send_password_reset)

        client = TestClient(app, base_url="http://localhost:8000")
        res = client.post("/api/auth/forgot-password", json={"email": email}, headers={"X-Forwarded-For": ip})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "reset_token" not in data, "CRITICAL: reset_token was leaked in API response!"
        assert "dev_note" not in data
        assert "If an account with that email exists" in data["message"]
        assert len(captured_reset_urls) == 1
        assert captured_reset_urls[0][0] == email
        assert "token=" in captured_reset_urls[0][1]

    def test_08_reset_token_hashed_in_storage(self):
        """8. Reset token is only stored as SHA-256 hash in storage (never raw)."""
        email = f"hashcheck_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "HashPassword123!"
        user, _, _ = self.auth_service.signup(email, pwd)
        assert user is not None

        raw_token, _ = self.auth_service.create_reset_token(email)
        assert raw_token is not None

        # Verify raw token is NOT in Redis as a key directly
        raw_key_val = self.store.client.get(f"pwd_reset:{raw_token}")
        assert raw_key_val is None, "Raw token must not be used as the storage key!"

        # Verify SHA-256 hash is the actual key
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        hashed_key_val = self.store.client.get(f"pwd_reset:{token_hash}")
        assert hashed_key_val is not None
        assert (hashed_key_val.decode("utf-8") if isinstance(hashed_key_val, bytes) else str(hashed_key_val)) == user["id"]

    def test_09_reset_link_has_raw_token_only_in_email_layer(self, monkeypatch):
        """9. Reset link has raw token only in email provider layer."""
        email = f"emaillink_{uuid.uuid4().hex[:8]}@example.com"
        ip = get_unique_ip()
        self.auth_service.signup(email, "SecretPassword123!")

        delivered_links = []
        monkeypatch.setattr(
            EmailProvider,
            "send_password_reset",
            lambda self_p, recip, link: delivered_links.append(link),
        )

        res = self.client.post("/api/auth/forgot-password", json={"email": email}, headers={"X-Forwarded-For": ip})
        assert res.status_code == 200
        assert len(delivered_links) == 1
        reset_link = delivered_links[0]
        assert "reset-password?token=" in reset_link

    def test_10_and_15_and_16_reset_valid_token_updates_password(self, monkeypatch):
        """10, 15, 16. Reset with valid token works, new password logs in, old password no longer works."""
        email = f"resetvalid_{uuid.uuid4().hex[:8]}@example.com"
        old_pwd = "OldPassword123!"
        new_pwd = "NewBrandNewPassword789!"
        ip = get_unique_ip()

        self.auth_service.signup(email, old_pwd)

        delivered = []
        monkeypatch.setattr(EmailProvider, "send_password_reset", lambda s, r, link: delivered.append(link))

        self.client.post("/api/auth/forgot-password", json={"email": email}, headers={"X-Forwarded-For": ip})
        assert len(delivered) == 1
        raw_token = delivered[0].split("token=")[1]

        # Reset password
        reset_res = self.client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "new_password": new_pwd},
            headers={"X-Forwarded-For": ip},
        )
        assert reset_res.status_code == 200
        assert reset_res.json()["status"] == "ok"

        # Old password fails
        login_old = self.client.post("/api/auth/login", json={"email": email, "password": old_pwd}, headers={"X-Forwarded-For": ip})
        assert login_old.status_code == 401

        # New password succeeds
        login_new = self.client.post("/api/auth/login", json={"email": email, "password": new_pwd}, headers={"X-Forwarded-For": ip})
        assert login_new.status_code == 200
        assert login_new.json()["user"]["email"] == email

    def test_11_reset_invalid_token_fails(self):
        """11. Reset with invalid/tampered token fails."""
        ip = get_unique_ip()
        res = self.client.post(
            "/api/auth/reset-password",
            json={"token": "totally_invalid_nonexistent_token_12345", "new_password": "NewSecurePassword123!"},
            headers={"X-Forwarded-For": ip},
        )
        assert res.status_code == 400
        assert "invalid or has expired" in res.json()["detail"].lower()

    def test_12_reset_expired_token_fails(self):
        """12. Reset with expired token fails."""
        email = f"expired_{uuid.uuid4().hex[:8]}@example.com"
        ip = get_unique_ip()
        self.auth_service.signup(email, "Password123!")

        # Create token
        raw_token, _ = self.auth_service.create_reset_token(email)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        
        # Explicitly set TTL to 0/expired in Redis
        self.store.client.delete(f"pwd_reset:{token_hash}")

        res = self.client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "new_password": "NewPassword123!"},
            headers={"X-Forwarded-For": ip},
        )
        assert res.status_code == 400
        assert "invalid or has expired" in res.json()["detail"].lower()

    def test_13_reset_token_cannot_be_reused(self, monkeypatch):
        """13. Reset token cannot be reused (one-time consumption)."""
        email = f"reuse_{uuid.uuid4().hex[:8]}@example.com"
        ip = get_unique_ip()
        self.auth_service.signup(email, "InitialPassword123!")

        delivered = []
        monkeypatch.setattr(EmailProvider, "send_password_reset", lambda s, r, link: delivered.append(link))

        self.client.post("/api/auth/forgot-password", json={"email": email}, headers={"X-Forwarded-For": ip})
        raw_token = delivered[0].split("token=")[1]

        # First reset succeeds
        r1 = self.client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "new_password": "PasswordOne123!"},
            headers={"X-Forwarded-For": ip},
        )
        assert r1.status_code == 200

        # Second reset with SAME token fails
        r2 = self.client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "new_password": "PasswordTwo456!"},
            headers={"X-Forwarded-For": ip},
        )
        assert r2.status_code == 400
        assert "invalid or has expired" in r2.json()["detail"].lower()

    def test_14_existing_sessions_revoked_on_password_reset(self, monkeypatch):
        """14. All existing sessions become invalid after password reset."""
        email = f"sessrev_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "SessionPass123!"
        ip = get_unique_ip()

        client1 = TestClient(app, base_url="http://localhost:8000")
        client2 = TestClient(app, base_url="http://localhost:8000")

        # Signup client1
        client1.post("/api/auth/signup", json={"email": email, "password": pwd}, headers={"X-Forwarded-For": ip})
        client1.post("/api/auth/login", json={"email": email, "password": pwd}, headers={"X-Forwarded-For": ip})
        assert client1.get("/api/auth/me", headers={"X-Forwarded-For": ip}).status_code == 200

        # Login client2
        client2.post("/api/auth/login", json={"email": email, "password": pwd}, headers={"X-Forwarded-For": ip})
        assert client2.get("/api/auth/me", headers={"X-Forwarded-For": ip}).status_code == 200

        delivered = []
        monkeypatch.setattr(EmailProvider, "send_password_reset", lambda s, r, link: delivered.append(link))

        # Request reset & change password
        client1.post("/api/auth/forgot-password", json={"email": email}, headers={"X-Forwarded-For": ip})
        raw_token = delivered[0].split("token=")[1]

        reset_res = client1.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "new_password": "NewSessionPass456!"},
            headers={"X-Forwarded-For": ip},
        )
        assert reset_res.status_code == 200

        # Both existing sessions must now be 401 Unauthorized!
        assert client1.get("/api/auth/me", headers={"X-Forwarded-For": ip}).status_code == 401
        assert client2.get("/api/auth/me", headers={"X-Forwarded-For": ip}).status_code == 401

    def test_17_logout_invalidates_session(self):
        """17. Logout invalidates server session and clears cookies."""
        email = f"logout_{uuid.uuid4().hex[:8]}@example.com"
        ip = get_unique_ip()
        client = TestClient(app, base_url="http://localhost:8000")

        client.post("/api/auth/signup", json={"email": email, "password": "Password123!"}, headers={"X-Forwarded-For": ip})
        login_res = client.post("/api/auth/login", json={"email": email, "password": "Password123!"}, headers={"X-Forwarded-For": ip})
        assert login_res.status_code == 200
        csrf = client.cookies.get("csrf_token")
        assert csrf is not None

        # Logout with CSRF
        res = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf, "X-Forwarded-For": ip})
        assert res.status_code == 200

        # /api/auth/me is now 401
        res_me = client.get("/api/auth/me", headers={"X-Forwarded-For": ip})
        assert res_me.status_code == 401

    def test_18_refresh_preserves_login(self):
        """18. Refresh preserves login while session cookie is valid."""
        email = f"refresh_{uuid.uuid4().hex[:8]}@example.com"
        ip = get_unique_ip()
        client = TestClient(app, base_url="http://localhost:8000")

        client.post("/api/auth/signup", json={"email": email, "password": "Password123!"}, headers={"X-Forwarded-For": ip})
        login_res = client.post("/api/auth/login", json={"email": email, "password": "Password123!"}, headers={"X-Forwarded-For": ip})
        assert login_res.status_code == 200

        # Simulate multiple page reloads / API checks with same cookies
        for _ in range(3):
            res_me = client.get("/api/auth/me", headers={"X-Forwarded-For": ip})
            assert res_me.status_code == 200
            assert res_me.json()["user"]["email"] == email

    def test_19_rate_limiting(self):
        """19. Rate limiting blocks excessive abuse attempts."""
        test_ip_key = f"bruteforce_{uuid.uuid4().hex[:6]}"
        limit = 3
        window = 5

        for _ in range(limit):
            allowed, _ = self.auth_service.check_rate_limit(test_ip_key, limit=limit, window_seconds=window)
            assert allowed is True

        allowed, retry_after = self.auth_service.check_rate_limit(test_ip_key, limit=limit, window_seconds=window)
        assert allowed is False
        assert retry_after > 0

    def test_20_password_reset_anti_enumeration(self, monkeypatch):
        """20. Password reset does not reveal whether an email exists."""
        nonexistent_email = f"nonexistent_{uuid.uuid4().hex[:8]}@example.com"
        existing_email = f"exists_{uuid.uuid4().hex[:8]}@example.com"
        ip1 = get_unique_ip()
        ip2 = get_unique_ip()

        self.auth_service.signup(existing_email, "ExistingPassword123!")

        monkeypatch.setattr(EmailProvider, "send_password_reset", lambda s, r, link: None)

        res_nonexistent = self.client.post("/api/auth/forgot-password", json={"email": nonexistent_email}, headers={"X-Forwarded-For": ip1})
        res_existing = self.client.post("/api/auth/forgot-password", json={"email": existing_email}, headers={"X-Forwarded-For": ip2})

        assert res_nonexistent.status_code == 200
        assert res_existing.status_code == 200
        # Both status and message MUST be completely identical!
        assert res_nonexistent.json() == res_existing.json()
        assert "reset_token" not in res_nonexistent.json()
        assert "reset_token" not in res_existing.json()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
