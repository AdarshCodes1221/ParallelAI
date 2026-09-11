#!/usr/bin/env python3
"""
Comprehensive 17-Point Verification Test Suite for:
1. Signup succeeds
2. Signup response contains NO session token
3. Signup does NOT create authenticated session (no cookies)
4. Immediately calling /me after signup without login returns 401
5. Login after signup succeeds
6. Forgot-password returns generic response
7. Forgot-password response contains NO reset_token
8. Mailpit receives the reset email
9. Reset email contains correct frontend reset URL
10. Reset token is hashed in database/storage
11. Reset token works once
12. Expired reset token fails
13. Reset password revokes old sessions
14. New password works
15. Old password fails
16. Logout works
17. Multi-user isolation remains intact
"""

import hashlib
import json
import os
import sys
import time
import urllib.request
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


def get_mailpit_api_url():
    """Find Mailpit REST API endpoint depending on environment (host vs container)."""
    settings = get_settings()
    candidates = []
    # If smtp_host is specified and not localhost, try that host
    if settings.smtp_host and settings.smtp_host not in ("localhost", "127.0.0.1"):
        candidates.append(f"http://{settings.smtp_host}:8025")
    candidates.append("http://localhost:8025")
    candidates.append("http://127.0.0.1:8025")
    candidates.append("http://mailpit:8025")

    for url in candidates:
        try:
            req = urllib.request.Request(f"{url}/api/v1/messages", headers={"User-Agent": "TestClient"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    return url
        except Exception:
            continue
    return None


class TestMailpitAndAuthFlow:
    @classmethod
    def setup_class(cls):
        cls.client = TestClient(app, base_url="http://localhost:8000")
        cls.store = RedisStore()
        cls.auth_service = AuthService(store=cls.store)
        cls.settings = get_settings()
        cls.mailpit_url = get_mailpit_api_url()

    # 1, 2, 3, 4: Signup does not authenticate user
    def test_01_to_04_signup_behavior(self):
        """
        1. Signup succeeds
        2. Signup response contains NO session token
        3. Signup does NOT create authenticated session
        4. Immediately calling /me after signup without login returns 401
        """
        email = f"signup_test_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "SafePassword123!"
        name = "Signup Tester"
        ip = get_unique_ip()

        client = TestClient(app, base_url="http://localhost:8000")
        res = client.post(
            "/api/auth/signup",
            json={"email": email, "password": pwd, "name": name},
            headers={"X-Forwarded-For": ip},
        )
        # 1. Signup succeeds
        assert res.status_code == 200, f"Signup failed: {res.text}"
        data = res.json()
        assert data["status"] == "ok"
        assert data["message"] == "Account created successfully. Please sign in."
        assert data["user"]["email"] == email

        # 2. Signup response contains NO session token
        assert "token" not in data, "Signup response must not contain token"
        assert "csrf_token" not in data, "Signup response must not contain csrf_token"
        assert "session_token" not in data, "Signup response must not contain session_token"

        # 3. Signup does NOT create authenticated session (no cookies set)
        assert "session_token" not in res.cookies, "HttpOnly session_token cookie was set on signup!"
        assert "session_token" not in client.cookies, "Client has session_token cookie after signup!"

        # 4. Immediately calling /me after signup without login returns 401
        me_res = client.get("/api/auth/me")
        assert me_res.status_code == 401, f"Expected 401 on /me after signup, got {me_res.status_code}"

    # 5. Login after signup succeeds
    def test_05_login_after_signup_succeeds(self):
        """5. Login after signup succeeds and establishes session."""
        email = f"login_test_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "SafePassword123!"
        ip = get_unique_ip()

        client = TestClient(app, base_url="http://localhost:8000")
        signup_res = client.post(
            "/api/auth/signup",
            json={"email": email, "password": pwd},
            headers={"X-Forwarded-For": ip},
        )
        assert signup_res.status_code == 200

        # Explicit login
        login_res = client.post(
            "/api/auth/login",
            json={"email": email, "password": pwd},
            headers={"X-Forwarded-For": ip},
        )
        assert login_res.status_code == 200
        assert "session_token" in client.cookies

        # Calling /me now succeeds
        me_res = client.get("/api/auth/me")
        assert me_res.status_code == 200
        assert me_res.json()["user"]["email"] == email

    # 6 & 7. Forgot-password returns generic response and no reset token
    def test_06_and_07_forgot_password_generic_no_token(self):
        """
        6. Forgot-password returns generic response
        7. Forgot-password response contains NO reset_token
        """
        email = f"forgot_test_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "SafePassword123!"
        ip = get_unique_ip()

        client = TestClient(app, base_url="http://localhost:8000")
        client.post("/api/auth/signup", json={"email": email, "password": pwd}, headers={"X-Forwarded-For": ip})

        res = client.post("/api/auth/forgot-password", json={"email": email}, headers={"X-Forwarded-For": ip})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        # 6. Generic response
        assert "If an account with that email exists" in data["message"]
        # 7. No reset token in response
        assert "reset_token" not in data
        assert "token" not in data

        # Unknown email returns identical generic response (anti-enumeration)
        res_unknown = client.post(
            "/api/auth/forgot-password",
            json={"email": f"unknown_{uuid.uuid4().hex[:8]}@example.com"},
            headers={"X-Forwarded-For": ip},
        )
        assert res_unknown.status_code == 200
        assert res_unknown.json() == data

    # 8 & 9. Mailpit receives the reset email with correct reset URL
    def test_08_and_09_mailpit_receives_reset_email(self):
        """
        8. Mailpit receives the reset email
        9. Reset email contains correct frontend reset URL
        """
        email = f"mailpit_user_{uuid.uuid4().hex[:8]}@parallel-ai.local"
        pwd = "SafePassword123!"
        ip = get_unique_ip()

        client = TestClient(app, base_url="http://localhost:8000")
        client.post("/api/auth/signup", json={"email": email, "password": pwd}, headers={"X-Forwarded-For": ip})

        # Clear mailpit messages if reachable
        mailpit_api = get_mailpit_api_url()
        if mailpit_api:
            try:
                req = urllib.request.Request(f"{mailpit_api}/api/v1/messages", method="DELETE")
                urllib.request.urlopen(req, timeout=2)
            except Exception:
                pass

        # Trigger forgot-password
        res = client.post("/api/auth/forgot-password", json={"email": email}, headers={"X-Forwarded-For": ip})
        assert res.status_code == 200

        if not mailpit_api:
            pytest.skip("Mailpit web API not reachable from this test environment; skipping live check")

        # Give SMTP 1 second to deliver
        time.sleep(1)

        # Query Mailpit for delivered message
        req = urllib.request.Request(f"{mailpit_api}/api/v1/messages")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        messages = data.get("messages", [])
        user_messages = [m for m in messages if any(email in t.get("Address", "") for t in m.get("To", []))]
        assert len(user_messages) >= 1, f"Expected reset email for {email} in Mailpit, found none."

        msg_id = user_messages[0]["ID"]
        # Fetch full message content
        detail_req = urllib.request.Request(f"{mailpit_api}/api/v1/message/{msg_id}")
        with urllib.request.urlopen(detail_req, timeout=3) as detail_resp:
            msg_data = json.loads(detail_resp.read().decode("utf-8"))

        # 8. Mailpit receives reset email with correct subject
        assert msg_data["Subject"] == "Reset your Parallel AI password"

        # 9. Reset email contains correct frontend reset URL
        body_text = msg_data.get("Text", "") + msg_data.get("HTML", "")
        expected_base = get_settings().password_reset_base_url
        assert expected_base in body_text, f"Expected {expected_base} in email body"
        assert "token=" in body_text, "Expected token query param in reset email"

    # 10. Reset token is hashed in database/storage
    def test_10_reset_token_is_hashed_in_storage(self):
        """10. Reset token is hashed in database/storage (SHA-256)."""
        email = f"hash_test_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "SafePassword123!"
        self.auth_service.signup(email, pwd)

        raw_token, _ = self.auth_service.create_reset_token(email)
        assert raw_token is not None

        # Verify raw token is NOT in Redis
        assert self.store.client.get(f"pwd_reset:{raw_token}") is None

        # Verify SHA-256 hashed token is in Redis
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        assert self.store.client.get(f"pwd_reset:{token_hash}") is not None

    # 11 & 12. Reset token works once; expired reset token fails
    def test_11_and_12_reset_token_one_time_and_expiry(self):
        """
        11. Reset token works once
        12. Expired reset token fails
        """
        email = f"onetime_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "OriginalPassword123!"
        ip = get_unique_ip()
        self.auth_service.signup(email, pwd)

        raw_token, _ = self.auth_service.create_reset_token(email)

        client = TestClient(app, base_url="http://localhost:8000")
        # First reset works
        res1 = client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "new_password": "NewValidPassword456!"},
            headers={"X-Forwarded-For": ip},
        )
        assert res1.status_code == 200

        # Second reset with SAME token fails (one-time use)
        res2 = client.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "new_password": "AnotherPassword789!"},
            headers={"X-Forwarded-For": ip},
        )
        assert res2.status_code == 400
        assert "invalid or has expired" in res2.json()["detail"].lower()

        # Expired token check
        raw_token2, _ = self.auth_service.create_reset_token(email)
        token_hash2 = hashlib.sha256(raw_token2.encode("utf-8")).hexdigest()
        # Delete to simulate expiration
        self.store.client.delete(f"pwd_reset:{token_hash2}")

        res3 = client.post(
            "/api/auth/reset-password",
            json={"token": raw_token2, "new_password": "AnotherPassword789!"},
            headers={"X-Forwarded-For": ip},
        )
        assert res3.status_code == 400
        assert "invalid or has expired" in res3.json()["detail"].lower()

    # 13, 14, 15: Reset password revokes old sessions; new works; old fails
    def test_13_to_15_session_revocation_and_credentials(self):
        """
        13. Reset password revokes old sessions
        14. New password works
        15. Old password fails
        """
        email = f"session_revoke_{uuid.uuid4().hex[:8]}@example.com"
        old_pwd = "OldPassword123!"
        new_pwd = "BrandNewPassword456!"
        ip = get_unique_ip()

        # Signup
        client_old = TestClient(app, base_url="http://localhost:8000")
        client_old.post("/api/auth/signup", json={"email": email, "password": old_pwd}, headers={"X-Forwarded-For": ip})

        # Login to establish active session
        login_old = client_old.post("/api/auth/login", json={"email": email, "password": old_pwd}, headers={"X-Forwarded-For": ip})
        assert login_old.status_code == 200
        assert client_old.get("/api/auth/me").status_code == 200

        # Reset password
        raw_token, _ = self.auth_service.create_reset_token(email)
        reset_res = client_old.post(
            "/api/auth/reset-password",
            json={"token": raw_token, "new_password": new_pwd},
            headers={"X-Forwarded-For": ip},
        )
        assert reset_res.status_code == 200

        # 13. Old session is now revoked
        assert client_old.get("/api/auth/me").status_code == 401

        # 15. Old password fails
        bad_login = client_old.post("/api/auth/login", json={"email": email, "password": old_pwd}, headers={"X-Forwarded-For": ip})
        assert bad_login.status_code == 401

        # 14. New password works
        client_new = TestClient(app, base_url="http://localhost:8000")
        good_login = client_new.post("/api/auth/login", json={"email": email, "password": new_pwd}, headers={"X-Forwarded-For": ip})
        assert good_login.status_code == 200
        assert client_new.get("/api/auth/me").status_code == 200

    # 16. Logout works
    def test_16_logout_works(self):
        """16. Logout works and deletes session."""
        email = f"logout_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "SafePassword123!"
        ip = get_unique_ip()

        client = TestClient(app, base_url="http://localhost:8000")
        client.post("/api/auth/signup", json={"email": email, "password": pwd}, headers={"X-Forwarded-For": ip})
        login_res = client.post("/api/auth/login", json={"email": email, "password": pwd}, headers={"X-Forwarded-For": ip})
        assert login_res.status_code == 200
        csrf_token = login_res.json()["csrf_token"]

        # Logout with CSRF
        logout_res = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_token, "X-Forwarded-For": ip})
        assert logout_res.status_code == 200

        # /me is now 401
        assert client.get("/api/auth/me").status_code == 401

    # 17. Multi-user isolation remains intact
    def test_17_multi_user_isolation(self):
        """17. Multi-user isolation: User A data is strictly inaccessible to User B."""
        email_a = f"alice_{uuid.uuid4().hex[:8]}@example.com"
        email_b = f"bob_{uuid.uuid4().hex[:8]}@example.com"
        pwd = "SafePassword123!"
        ip = get_unique_ip()

        # User A signup & login
        client_a = TestClient(app, base_url="http://localhost:8000")
        client_a.post("/api/auth/signup", json={"email": email_a, "password": pwd}, headers={"X-Forwarded-For": ip})
        res_a = client_a.post("/api/auth/login", json={"email": email_a, "password": pwd}, headers={"X-Forwarded-For": ip})
        csrf_a = res_a.json()["csrf_token"]

        # User B signup & login
        client_b = TestClient(app, base_url="http://localhost:8000")
        client_b.post("/api/auth/signup", json={"email": email_b, "password": pwd}, headers={"X-Forwarded-For": ip})
        res_b = client_b.post("/api/auth/login", json={"email": email_b, "password": pwd}, headers={"X-Forwarded-For": ip})
        csrf_b = res_b.json()["csrf_token"]

        # User A creates a session
        sess_res = client_a.post("/api/sessions", json={"title": "Alice Private Session"}, headers={"X-CSRF-Token": csrf_a, "X-Forwarded-For": ip})
        assert sess_res.status_code == 200
        session_id_a = sess_res.json()["id"]

        # User B lists sessions - MUST NOT see User A's session
        b_sessions = client_b.get("/api/sessions", headers={"X-Forwarded-For": ip}).json()["sessions"]
        assert not any(s["id"] == session_id_a for s in b_sessions), "User B saw User A's session!"

        # User B direct access to User A's session - MUST return 404
        direct_res = client_b.get(f"/api/sessions/{session_id_a}", headers={"X-Forwarded-For": ip})
        assert direct_res.status_code == 404, "User B should receive 404 for User A session"
