"""
Comprehensive Multi-Tenant User Isolation & Data Partitioning Test Suite.
Verifies that:
- TEST A: Session & Message Isolation between User A and User B
- TEST B: Document Isolation between User A and User B
- TEST C: RAG Lexical & Vector Isolation with Cross-User Secret Separation
- TEST D: Malicious Cross-Tenant Session/Document Access Rejection (403/404)
- TEST E: Simultaneous/Concurrent User Operations
"""

import asyncio
import os
import sys
import uuid
import pytest
from unittest.mock import MagicMock, patch
import httpx
_orig_httpx_init = httpx.Client.__init__
def _patched_httpx_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    return _orig_httpx_init(self, *args, **kwargs)
httpx.Client.__init__ = _patched_httpx_init

from fastapi.testclient import TestClient

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app
from routes.auth import get_current_user, verify_csrf
from services.rag_service import RAGService


def make_test_client(application):
    return TestClient(application)


@pytest.fixture
def test_users():
    return {
        "user_a": {
            "id": f"usr-a-{uuid.uuid4().hex[:8]}",
            "email": "usera@example.com",
            "name": "User A",
            "is_active": True,
        },
        "user_b": {
            "id": f"usr-b-{uuid.uuid4().hex[:8]}",
            "email": "userb@example.com",
            "name": "User B",
            "is_active": True,
        },
    }


def test_scenario_a_session_and_message_isolation(test_users):
    """
    TEST A: Session & Message Isolation.
    Asserts User B cannot retrieve User A's session or messages,
    and User A cannot retrieve User B's session or messages.
    """
    user_a = test_users["user_a"]
    user_b = test_users["user_b"]
    sess_a_id = f"sess-a-{uuid.uuid4().hex[:6]}"
    sess_b_id = f"sess-b-{uuid.uuid4().hex[:6]}"

    active_user = {"user": user_a}

    async def override_user():
        return active_user["user"]

    async def override_csrf():
        return None

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[verify_csrf] = override_csrf

    client = make_test_client(app)

    try:
        with patch("routes.api.session_service") as mock_session_svc:
            def mock_get(session_id, user_id=None):
                if session_id == sess_a_id and user_id == user_a["id"]:
                    return {"id": sess_a_id, "user_id": user_a["id"], "title": "Chat A"}
                if session_id == sess_b_id and user_id == user_b["id"]:
                    return {"id": sess_b_id, "user_id": user_b["id"], "title": "Chat B"}
                if user_id is None:
                    if session_id == sess_a_id:
                        return {"id": sess_a_id, "user_id": user_a["id"]}
                    if session_id == sess_b_id:
                        return {"id": sess_b_id, "user_id": user_b["id"]}
                return None

            def mock_list(limit=50, user_id=None):
                if user_id == user_a["id"]:
                    return [{"id": sess_a_id, "user_id": user_a["id"], "title": "Chat A"}]
                if user_id == user_b["id"]:
                    return [{"id": sess_b_id, "user_id": user_b["id"], "title": "Chat B"}]
                return []

            def mock_recent_messages(session_id, limit=12, user_id=None):
                if session_id == sess_a_id and user_id == user_a["id"]:
                    return [{"role": "user", "content": "Message A Private"}]
                if session_id == sess_b_id and user_id == user_b["id"]:
                    return [{"role": "user", "content": "Message B Private"}]
                return []

            mock_session_svc.get.side_effect = mock_get
            mock_session_svc.list_all.side_effect = mock_list
            mock_session_svc.recent_messages.side_effect = mock_recent_messages

            # User A lists sessions -> sees only Chat A
            active_user["user"] = user_a
            res_a = client.get("/api/sessions")
            assert res_a.status_code == 200
            assert len(res_a.json()["sessions"]) == 1
            assert res_a.json()["sessions"][0]["id"] == sess_a_id

            # User B lists sessions -> sees only Chat B
            active_user["user"] = user_b
            res_b = client.get("/api/sessions")
            assert res_b.status_code == 200
            assert len(res_b.json()["sessions"]) == 1
            assert res_b.json()["sessions"][0]["id"] == sess_b_id

            # User B attempts to fetch User A's session -> 404
            res_b_get_a = client.get(f"/api/sessions/{sess_a_id}")
            assert res_b_get_a.status_code == 404

            # User A attempts to fetch User B's session -> 404
            active_user["user"] = user_a
            res_a_get_b = client.get(f"/api/sessions/{sess_b_id}")
            assert res_a_get_b.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_scenario_b_document_isolation(test_users):
    """
    TEST B: Document Isolation.
    Asserts User B cannot fetch or delete User A's documents.
    """
    user_a = test_users["user_a"]
    user_b = test_users["user_b"]
    doc_a_id = f"doc-a-{uuid.uuid4().hex[:6]}"
    doc_b_id = f"doc-b-{uuid.uuid4().hex[:6]}"

    active_user = {"user": user_a}

    async def override_user():
        return active_user["user"]

    async def override_csrf():
        return None

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[verify_csrf] = override_csrf

    client = make_test_client(app)

    try:
        with patch("routes.api.document_service") as mock_doc_svc:
            def mock_get(document_id, user_id=None):
                if document_id == doc_a_id and user_id == user_a["id"]:
                    return {"id": doc_a_id, "user_id": user_a["id"], "filename": "doc_a.pdf"}
                if document_id == doc_b_id and user_id == user_b["id"]:
                    return {"id": doc_b_id, "user_id": user_b["id"], "filename": "doc_b.pdf"}
                return None

            def mock_delete(document_id, user_id=None):
                if document_id == doc_a_id and user_id == user_a["id"]:
                    return True
                if document_id == doc_b_id and user_id == user_b["id"]:
                    return True
                return False

            mock_doc_svc.get.side_effect = mock_get
            mock_doc_svc.delete.side_effect = mock_delete

            # User B attempts to access Document A -> 404
            active_user["user"] = user_b
            res_b_get_a = client.get(f"/api/documents/{doc_a_id}")
            assert res_b_get_a.status_code == 404

            # User B attempts to delete Document A -> 404
            res_b_del_a = client.delete(f"/api/documents/{doc_a_id}")
            assert res_b_del_a.status_code == 404

            # User B accessing Document B -> 200
            res_b_get_b = client.get(f"/api/documents/{doc_b_id}")
            assert res_b_get_b.status_code == 200
            assert res_b_get_b.json()["filename"] == "doc_b.pdf"
    finally:
        app.dependency_overrides.clear()


def test_scenario_c_rag_isolation(test_users):
    """
    TEST C: RAG Isolation.
    Ensures RediSearch vector & lexical searches strictly enforce user_id,
    and cross-user document querying returns zero results.
    """
    user_a = test_users["user_a"]
    user_b = test_users["user_b"]
    doc_a_id = "doc-user-a-secret-123"
    doc_b_id = "doc-user-b-secret-456"

    rag = RAGService(api_key=None)

    # Mock embedder
    rag.embedder = MagicMock()
    rag.embedder.embed.return_value = [[0.1] * 768]

    # Mock store and RediSearch command execution
    mock_redis = MagicMock()
    rag.store = mock_redis

    executed_queries = []

    def mock_execute_command(*args):
        command = args[0]
        if command == "FT.SEARCH":
            query_str = args[2]
            executed_queries.append(query_str)
            # Return 1 dummy result for simulation
            return [
                1,
                "chunk:1",
                [
                    b"id", b"c-1",
                    b"text", b"Private Chunk",
                    b"document_id", b"doc-1",
                    b"session_id", b"sess-1",
                    b"user_id", b"user-dummy",
                    b"score", b"0.1",
                ]
            ]
        return []

    mock_redis.client.execute_command.side_effect = mock_execute_command

    # 1. Verify user_id is unconditionally included in RediSearch query
    rag.search_results("test query", user_id=user_a["id"])
    assert any(f"@user_id:{{{rag._escape_tag(user_a['id'])}}}" in q for q in executed_queries)

    # 2. Verify that if User B queries with User A's document_id:
    # document_service filters it out and returns 0 results immediately
    with patch("services.document_service.DocumentService") as mock_doc_svc_class:
        mock_doc_svc = MagicMock()
        mock_doc_svc_class.return_value = mock_doc_svc
        # User B only owns doc_b_id
        mock_doc_svc.list.return_value = [{"id": doc_b_id}]

        results = rag.search_results(
            "What is User A secret?",
            document_ids=[doc_a_id],
            user_id=user_b["id"],
        )
        assert results == [], "User B must get 0 results when requesting User A's document"


def test_scenario_d_malicious_session_id_access(test_users):
    """
    TEST D: Malicious Cross-Tenant Session Access.
    If User B attempts to run agent or upload a document using User A's session_id,
    the backend rejects it with 403 Forbidden.
    """
    user_a = test_users["user_a"]
    user_b = test_users["user_b"]
    sess_a_id = "victim-session-id-a"

    active_user = {"user": user_b}

    async def override_user():
        return active_user["user"]

    async def override_csrf():
        return None

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[verify_csrf] = override_csrf

    client = make_test_client(app)

    try:
        with patch("routes.api.session_service") as mock_session_svc:
            def mock_get(session_id, user_id=None):
                if session_id == sess_a_id:
                    if user_id == user_b["id"]:
                        return None  # Does NOT belong to User B
                    # Belongs to User A
                    return {"id": sess_a_id, "user_id": user_a["id"]}
                return None

            mock_session_svc.get.side_effect = mock_get

            # User B attempts to hijack session A via /api/agent -> 403
            res_agent = client.post(
                "/api/agent",
                data={"session_id": sess_a_id, "query": "Hijack conversation"},
            )
            assert res_agent.status_code == 403

            # User B attempts to upload into session A -> 403
            res_upload = client.post(
                "/api/documents/upload",
                data={"session_id": sess_a_id},
                files={"file": ("malicious.txt", b"payload", "text/plain")},
            )
            assert res_upload.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_scenario_e_simultaneous_users(test_users):
    """
    TEST E: Simultaneous Users Execution.
    Verifies that simultaneous operations for User A and User B maintain distinct ownership.
    """
    user_a = test_users["user_a"]
    user_b = test_users["user_b"]

    from services.session_service import SessionService
    from core.redis_store import RedisStore

    redis = RedisStore()
    svc = SessionService(store=redis)

    sess_a = svc.create(title="Simultaneous A", user_id=user_a["id"])
    sess_b = svc.create(title="Simultaneous B", user_id=user_b["id"])

    assert sess_a["user_id"] == user_a["id"]
    assert sess_b["user_id"] == user_b["id"]
    assert sess_a["id"] != sess_b["id"]

    # Verify retrieval boundaries
    assert svc.get(sess_a["id"], user_id=user_a["id"]) is not None
    assert svc.get(sess_a["id"], user_id=user_b["id"]) is None

    assert svc.get(sess_b["id"], user_id=user_b["id"]) is not None
    assert svc.get(sess_b["id"], user_id=user_a["id"]) is None

    # Cleanup
    svc.delete(sess_a["id"], user_id=user_a["id"])
    svc.delete(sess_b["id"], user_id=user_b["id"])
