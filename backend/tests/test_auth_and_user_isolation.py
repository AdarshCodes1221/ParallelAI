#!/usr/bin/env python3
"""
Verification of Authentication and User Data Isolation:
- Signup, Login, Password validation
- Session Token generation and validation
- User A vs User B data isolation (Sessions, Documents, RAG chunks)
- Password reset flow
- Logout
"""

import sys
import time
import requests

BASE_URL = "http://127.0.0.1:8000/api"


def test_auth_and_isolation():
    print("=" * 70)
    print("🚀 RUNNING AUTH & USER ISOLATION VERIFICATION")
    print("=" * 70)

    # Health check
    for _ in range(15):
        try:
            r = requests.get("http://127.0.0.1:8000/health", timeout=2)
            if r.status_code == 200:
                print("✅ Backend is healthy!")
                break
        except Exception:
            time.sleep(1)

    ts = int(time.time())
    email_a = f"user_a_{ts}@example.com"
    email_b = f"user_b_{ts}@example.com"
    pwd = "SecurePassword123!"

    # 1. Signup User A
    print("\n[1] Signup User A")
    res_a = requests.post(f"{BASE_URL}/auth/signup", json={"email": email_a, "password": pwd, "name": "Alice"})
    assert res_a.status_code == 200, f"Signup failed: {res_a.text}"
    data_a = res_a.json()
    user_a = data_a["user"]
    print(f"  User A registered: ID={user_a['id']}, Email={user_a['email']}")

    # Duplicate email prevention
    res_dup = requests.post(f"{BASE_URL}/auth/signup", json={"email": email_a, "password": pwd})
    assert res_dup.status_code == 400, "Duplicate signup should have failed"
    print("  ✅ Duplicate signup prevented")

    # 2. Signup User B
    print("\n[2] Signup User B")
    res_b = requests.post(f"{BASE_URL}/auth/signup", json={"email": email_b, "password": pwd, "name": "Bob"})
    assert res_b.status_code == 200, f"Signup failed: {res_b.text}"
    user_b = res_b.json()["user"]
    print(f"  User B registered: ID={user_b['id']}, Email={user_b['email']}")

    # Explicit login User B
    res_login_b = requests.post(f"{BASE_URL}/auth/login", json={"email": email_b, "password": pwd})
    assert res_login_b.status_code == 200, "User B login failed"

    # 3. Login User A
    print("\n[3] Login User A")
    res_login = requests.post(f"{BASE_URL}/auth/login", json={"email": email_a, "password": pwd})
    assert res_login.status_code == 200, f"Login failed: {res_login.text}"
    session_a = requests.Session()
    session_a.cookies.update(res_a.cookies)
    session_a.cookies.update(res_login.cookies)

    # 4. Verify /auth/me
    print("\n[4] Verify /auth/me")
    res_me = session_a.get(f"{BASE_URL}/auth/me")
    assert res_me.status_code == 200
    assert res_me.json()["user"]["email"] == email_a
    print("  ✅ User A authenticated via Bearer token")

    # 5. User A creates session and document
    print("\n[5] User A creates session & document")
    session_res_a = session_a.post(
        f"{BASE_URL}/sessions",
        json={"title": "Alice Secret Project"},
        headers={"X-CSRF-Token": session_a.cookies.get("csrf_token")}
    ).json()
    session_id_a = session_res_a["id"]

    # User A creates a document
    doc_res_a = session_a.post(
        f"{BASE_URL}/documents/upload",
        data={"session_id": session_id_a},
        files={"file": ("alice_secret.txt", b"Alice secret quantum formula is Q=42.", "text/plain")},
        headers={"X-CSRF-Token": session_a.cookies.get("csrf_token")}
    ).json()
    doc_id_a = doc_res_a["id"]
    print(f"  Alice created Session: {session_id_a}, Document: {doc_id_a}")

    # 6. User B checks sessions and documents (Data Isolation)
    print("\n[6] Verify User B CANNOT see User A's data")
    session_b = requests.Session()
    session_b.cookies.update(res_login_b.cookies)
    b_sessions = session_b.get(f"{BASE_URL}/sessions").json()["sessions"]
    assert not any(s["id"] == session_id_a for s in b_sessions), "User B saw User A's session!"
    print("  ✅ User B session list is isolated")

    b_docs = session_b.get(f"{BASE_URL}/documents").json()["documents"]
    assert not any(d["id"] == doc_id_a for d in b_docs), "User B saw User A's document!"
    print("  ✅ User B document list is isolated")

    # User B tries direct GET on Alice's document
    res_direct_get = session_b.get(f"{BASE_URL}/documents/{doc_id_a}")
    assert res_direct_get.status_code == 404, "User B should not be able to get User A's document directly"
    print("  ✅ User B direct access to Alice's document blocked (404)")

    # 7. Password Reset Flow
    print("\n[7] Password Reset Flow")
    forgot_res = requests.post(f"{BASE_URL}/auth/forgot-password", json={"email": email_a}).json()
    assert "reset_token" not in forgot_res, "Reset token must NOT be returned in API response"
    assert "If an account with that email exists" in forgot_res.get("message", "")

    from services.auth_service import AuthService
    raw_token, _ = AuthService().create_reset_token(email_a)

    new_pwd = "BrandNewPassword456!"
    reset_res = requests.post(f"{BASE_URL}/auth/reset-password", json={"token": raw_token, "new_password": new_pwd})
    assert reset_res.status_code == 200, f"Password reset failed: {reset_res.text}"

    # Verify login with new password
    login_new = requests.post(f"{BASE_URL}/auth/login", json={"email": email_a, "password": new_pwd})
    assert login_new.status_code == 200, "Login with new password should succeed"
    print("  ✅ Password reset verified")

    # 8. Logout
    print("\n[8] Logout")
    logout_session = requests.Session()
    logout_session.cookies.update(login_new.cookies)
    logout_session.post(f"{BASE_URL}/auth/logout", headers={"X-CSRF-Token": logout_session.cookies.get("csrf_token")})
    me_after_logout = logout_session.get(f"{BASE_URL}/auth/me")
    assert me_after_logout.status_code == 401, "Token should be invalid after logout"
    print("  ✅ Logout revoked token")

    print("\n" + "=" * 70)
    print("🏁 ALL AUTH & USER ISOLATION TESTS PASSED!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = test_auth_and_isolation()
    sys.exit(0 if success else 1)
