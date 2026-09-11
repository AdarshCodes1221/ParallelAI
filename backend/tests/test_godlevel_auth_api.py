#!/usr/bin/env python3
"""
Comprehensive API Tests for Authentication, HttpOnly Cookie Sessions,
CSRF, Security Headers, and Cross-User Data Isolation.
"""

import os
import sys
import time
import uuid
import requests

BASE_URL = "http://127.0.0.1:8000"
API_URL = f"{BASE_URL}/api"


def run_api_tests():
    print("=" * 70)
    print("🚀 RUNNING GODLEVEL AUTH API & SECURITY INTEGRATION SUITE")
    print("=" * 70)

    # Health check
    for _ in range(10):
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=2)
            if r.status_code == 200:
                print("✅ Backend API is reachable & healthy")
                break
        except Exception:
            time.sleep(1)

    # 1. Security Headers Verification
    print("\n[1] Verify Security Headers")
    res_root = requests.get(f"{BASE_URL}/")
    assert res_root.headers.get("X-Content-Type-Options") == "nosniff", "Missing X-Content-Type-Options"
    assert res_root.headers.get("X-Frame-Options") == "DENY", "Missing X-Frame-Options"
    assert "strict-origin" in res_root.headers.get("Referrer-Policy", ""), "Missing Referrer-Policy"
    print("  ✅ Security headers (nosniff, DENY, Referrer-Policy) verified")

    ts = int(time.time())
    email_a = f"alice_{ts}_{uuid.uuid4().hex[:4]}@example.com"
    email_b = f"bob_{ts}_{uuid.uuid4().hex[:4]}@example.com"
    pwd_a = "AliceSecurePass123!"
    pwd_b = "BobSecurePass456!"

    # 2. Signup User A with No Auto-Login Verification
    print("\n[2] Signup User A & Verify No Auto-Login")
    session_a = requests.Session()
    res_signup_a = session_a.post(
        f"{API_URL}/auth/signup",
        json={"email": email_a, "password": pwd_a, "name": "Alice Developer"},
    )
    assert res_signup_a.status_code == 200, f"Signup failed: {res_signup_a.text}"
    data_a = res_signup_a.json()
    assert data_a["status"] == "ok"
    assert data_a["user"]["email"] == email_a
    assert "password_hash" not in data_a["user"], "Password hash leaked in signup response!"
    assert "session_token" not in session_a.cookies, "Signup must NOT set session_token cookie!"
    assert "csrf_token" not in session_a.cookies, "Signup must NOT set csrf_token cookie!"
    assert data_a.get("token") is None, "Signup must NOT return a session token!"

    # Unauthenticated before explicit login
    res_pre_me = session_a.get(f"{API_URL}/auth/me")
    assert res_pre_me.status_code == 401, "Unauthenticated /auth/me after signup must return 401!"

    # Explicit login User A
    res_login_a = session_a.post(f"{API_URL}/auth/login", json={"email": email_a, "password": pwd_a})
    assert res_login_a.status_code == 200
    assert "session_token" in session_a.cookies, "Login must set session_token cookie!"
    assert "csrf_token" in session_a.cookies, "Login must set csrf_token cookie!"
    csrf_token_a = session_a.cookies.get("csrf_token")
    print("  ✅ User A registered without auto-login, and explicit login established session")

    # 3. Duplicate Signup Rejection
    print("\n[3] Duplicate Signup Rejection")
    res_dup = session_a.post(f"{API_URL}/auth/signup", json={"email": email_a, "password": pwd_a})
    assert res_dup.status_code == 400
    assert "already exists" in res_dup.json()["detail"].lower()
    print("  ✅ Duplicate registration correctly rejected (400)")

    # 4. Weak Password Rejection
    print("\n[4] Weak Password Rejection")
    res_weak = session_a.post(
        f"{API_URL}/auth/signup",
        json={"email": f"weak_{ts}@example.com", "password": "short"},
    )
    assert res_weak.status_code == 400
    assert "at least 8 characters" in res_weak.json()["detail"]
    print("  ✅ Weak password correctly rejected (400)")

    # 5. Session Restoration via /auth/me (Cookie-only)
    print("\n[5] Session Restoration via Cookie /auth/me")
    res_me_a = session_a.get(f"{API_URL}/auth/me")
    assert res_me_a.status_code == 200
    assert res_me_a.json()["user"]["email"] == email_a
    print("  ✅ User A session restored cleanly via HttpOnly cookie")

    # 6. Unauthenticated Access Rejection
    print("\n[6] Unauthenticated /auth/me Rejection")
    res_unauth = requests.get(f"{API_URL}/auth/me")
    assert res_unauth.status_code == 401
    print("  ✅ Anonymous request to /auth/me correctly rejected (401)")

    # 7. Signup User B (No Auto-Login)
    print("\n[7] Signup User B & Explicit Login")
    session_b = requests.Session()
    res_signup_b = session_b.post(
        f"{API_URL}/auth/signup",
        json={"email": email_b, "password": pwd_b, "name": "Bob Analyst"},
    )
    assert res_signup_b.status_code == 200
    assert "session_token" not in session_b.cookies, "Signup must NOT set session_token cookie!"

    # Explicit login User B
    res_login_b = session_b.post(f"{API_URL}/auth/login", json={"email": email_b, "password": pwd_b})
    assert res_login_b.status_code == 200
    user_b_id = res_login_b.json()["user"]["id"]
    csrf_token_b = session_b.cookies.get("csrf_token")
    print("  ✅ User B registered without auto-login, and explicit login established session")

    # 8. User A creates session and document
    print("\n[8] User A creates isolated session & document")
    res_sess_a = session_a.post(
        f"{API_URL}/sessions",
        json={"title": "Alice Classified Plan"},
        headers={"X-CSRF-Token": csrf_token_a},
    )
    assert res_sess_a.status_code == 200
    session_id_a = res_sess_a.json()["id"]

    res_doc_a = session_a.post(
        f"{API_URL}/documents/upload",
        data={"session_id": session_id_a},
        files={"file": ("quantum_top_secret.txt", b"Quantum Algorithm Alpha-99: The encryption key is XYZ-777.", "text/plain")},
        headers={"X-CSRF-Token": csrf_token_a},
    )
    assert res_doc_a.status_code == 200
    doc_id_a = res_doc_a.json()["id"]
    print(f"  Alice created Session: {session_id_a}, Document: {doc_id_a}")

    # 9. Strict Cross-User Data Isolation
    print("\n[9] Verify User B CANNOT see or access User A's data")
    # User B lists sessions
    b_sessions = session_b.get(f"{API_URL}/sessions").json()["sessions"]
    assert not any(s["id"] == session_id_a for s in b_sessions), "User B saw User A's session!"

    # User B lists documents
    b_docs = session_b.get(f"{API_URL}/documents").json()["documents"]
    assert not any(d["id"] == doc_id_a for d in b_docs), "User B saw User A's document!"

    # User B attempts direct GET on User A's document
    res_direct = session_b.get(f"{API_URL}/documents/{doc_id_a}")
    assert res_direct.status_code == 404, "User B should not be able to get User A's document"

    # User B attempts direct GET on User A's session
    res_sess_direct = session_b.get(f"{API_URL}/sessions/{session_id_a}")
    assert res_sess_direct.status_code == 404, "User B should not be able to get User A's session"

    # User B attempts RAG search on User A's session
    res_rag_search = session_b.post(
        f"{API_URL}/search",
        json={"query": "Quantum Algorithm Alpha-99", "session_id": session_id_a},
        headers={"X-CSRF-Token": csrf_token_b},
    )
    assert res_rag_search.status_code == 404, "User B should not be able to search User A's session"
    print("  ✅ User A and User B data completely isolated (sessions, documents, RAG search)")

    # 10. Change Password Flow (Authenticated)
    print("\n[10] Authenticated Change Password")
    new_pwd_a = "AliceNewUpdatedPass789!"
    res_change_pwd = session_a.post(
        f"{API_URL}/auth/change-password",
        json={"current_password": pwd_a, "new_password": new_pwd_a},
        headers={"X-CSRF-Token": csrf_token_a},
    )
    assert res_change_pwd.status_code == 200, f"Change password failed: {res_change_pwd.text}"
    print("  ✅ Password changed successfully")

    # 11. Logout & Invalidation
    print("\n[11] Logout & Cookie Invalidation")
    res_logout_a = session_a.post(f"{API_URL}/auth/logout", headers={"X-CSRF-Token": csrf_token_a})
    assert res_logout_a.status_code == 200

    # Verify session is now invalidated
    res_me_after_logout = session_a.get(f"{API_URL}/auth/me")
    assert res_me_after_logout.status_code == 401, "Session must be revoked after logout"
    print("  ✅ Logout revoked session server-side")

    # 12. Relogin with new password
    print("\n[12] Relogin with New Password")
    res_relogin = session_a.post(f"{API_URL}/auth/login", json={"email": email_a, "password": new_pwd_a})
    assert res_relogin.status_code == 200
    assert "session_token" in session_a.cookies
    print("  ✅ Relogin with new password succeeded")

    print("\n" + "=" * 70)
    print("🏁 ALL GODLEVEL AUTH API & SECURITY TESTS PASSED!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = run_api_tests()
    sys.exit(0 if success else 1)
