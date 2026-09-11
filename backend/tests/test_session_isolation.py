import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app
from routes.auth import get_current_user, verify_csrf

client = TestClient(app)


def test_session_isolation_and_ownership():
    """
    Test user isolation:
    1. User A lists sessions (receives User A sessions only).
    2. User B tries to read, rename, or delete User A's session -> denied / not found.
    3. User B lists sessions (receives User B sessions only).
    """
    user_a_id = "user-uuid-a"
    user_b_id = "user-uuid-b"
    user_a_session_id = "session-a-1"
    user_b_session_id = "session-b-1"

    current_test_user = {"user": None}

    async def override_get_current_user():
        if not current_test_user["user"]:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current_test_user["user"]

    async def override_verify_csrf():
        return None

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[verify_csrf] = override_verify_csrf

    try:
        with patch("routes.api.session_service") as mock_session_svc:
            # Mock list_all
            def list_all_side_effect(user_id=None):
                if user_id == user_a_id:
                    return [{"id": user_a_session_id, "title": "User A Chat", "created_at": "2026-09-11"}]
                elif user_id == user_b_id:
                    return [{"id": user_b_session_id, "title": "User B Chat", "created_at": "2026-09-11"}]
                return []

            mock_session_svc.list_all.side_effect = list_all_side_effect

            # Mock get_session
            def get_session_side_effect(session_id, user_id=None):
                if session_id == user_a_session_id and user_id == user_a_id:
                    return {"id": user_a_session_id, "title": "User A Chat", "user_id": user_a_id}
                if session_id == user_b_session_id and user_id == user_b_id:
                    return {"id": user_b_session_id, "title": "User B Chat", "user_id": user_b_id}
                return None

            mock_session_svc.get.side_effect = get_session_side_effect
            mock_session_svc.recent_messages.return_value = [{"role": "user", "content": "secret a"}]

            # Mock update session
            def update_session_side_effect(session_id, title=None, user_id=None):
                if session_id == user_a_session_id and user_id == user_a_id:
                    return {"id": user_a_session_id, "title": title}
                if session_id == user_b_session_id and user_id == user_b_id:
                    return {"id": user_b_session_id, "title": title}
                return None

            mock_session_svc.update.side_effect = update_session_side_effect

            # Mock delete session
            def delete_session_side_effect(session_id, user_id=None):
                if session_id == user_a_session_id and user_id == user_a_id:
                    return True
                if session_id == user_b_session_id and user_id == user_b_id:
                    return True
                return False

            mock_session_svc.delete.side_effect = delete_session_side_effect

            # --- STEP 1: User A requests sessions ---
            current_test_user["user"] = {
                "id": user_a_id,
                "email": "usera@example.com",
                "full_name": "User A",
                "is_active": True,
                "is_verified": True
            }
            res_a = client.get("/api/sessions")
            assert res_a.status_code == 200
            data_a = res_a.json()["sessions"]
            assert len(data_a) == 1
            assert data_a[0]["id"] == user_a_session_id

            # --- STEP 2: User B tries to access User A's session ---
            current_test_user["user"] = {
                "id": user_b_id,
                "email": "userb@example.com",
                "full_name": "User B",
                "is_active": True,
                "is_verified": True
            }
            
            # User B listing sessions should only return User B's sessions
            res_b_list = client.get("/api/sessions")
            assert res_b_list.status_code == 200
            data_b = res_b_list.json()["sessions"]
            assert len(data_b) == 1
            assert data_b[0]["id"] == user_b_session_id

            # User B attempting to fetch User A's session details -> 404 Not Found
            res_b_get_a = client.get(f"/api/sessions/{user_a_session_id}")
            assert res_b_get_a.status_code == 404

            # User B attempting to rename User A's session -> 404 Not Found
            res_b_patch_a = client.patch(
                f"/api/sessions/{user_a_session_id}",
                json={"title": "Hacked Title"}
            )
            assert res_b_patch_a.status_code == 404

            # User B attempting to delete User A's session -> 404 Not Found
            res_b_del_a = client.delete(
                f"/api/sessions/{user_a_session_id}"
            )
            assert res_b_del_a.status_code == 404

            # --- STEP 3: User B modifying their own session succeeds ---
            res_b_patch_b = client.patch(
                f"/api/sessions/{user_b_session_id}",
                json={"title": "Updated User B Title"}
            )
            assert res_b_patch_b.status_code == 200
            assert res_b_patch_b.json()["session"]["title"] == "Updated User B Title"

            res_b_del_b = client.delete(
                f"/api/sessions/{user_b_session_id}"
            )
            assert res_b_del_b.status_code == 200
            assert res_b_del_b.json()["status"] == "deleted"
    finally:
        app.dependency_overrides.clear()
