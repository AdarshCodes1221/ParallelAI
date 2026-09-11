"""Container-native PostgreSQL/Redis persistence integration test.

Run with:
    docker compose exec -T backend python -m pytest -q /app/tests/test_live_persistence.py

The test uses only services reachable from the backend container. Backend
restart verification is opt-in because the container intentionally has no
Docker socket or Docker CLI.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import fitz
import psycopg
from psycopg.rows import dict_row
import pytest
import redis
import requests


BASE_URL = os.getenv("PERSISTENCE_TEST_BASE_URL", "http://backend:8000")
DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")


def _wait_for_health(timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{BASE_URL}/health", timeout=3)
            if response.ok:
                return
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(1)
    raise AssertionError(f"Backend did not become healthy within {timeout}s: {last_error}")


def _create_pdf() -> bytes:
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "Durable PostgreSQL document. CGPA 9.1.")
        return document.tobytes()
    finally:
        document.close()


def _db_one(query: str, params: tuple = ()):
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        return connection.execute(query, params).fetchone()


def _db_cleanup(user_id: str | None, tenant_id: str | None) -> None:
    if not user_id:
        return
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("DELETE FROM users WHERE id = %s", (user_id,))
    if tenant_id:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))


def _streamed_text(response: requests.Response) -> str:
    tokens: list[str] = []
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        try:
            event = json.loads(line[6:])
        except ValueError:
            continue
        if event.get("type") == "token":
            tokens.append(event.get("token", ""))
    return "".join(tokens)


def _optional_backend_restart() -> None:
    if os.getenv("PERSISTENCE_TEST_RESTART") != "1":
        return
    if not shutil.which("docker"):
        pytest.skip("PERSISTENCE_TEST_RESTART=1 requires Docker CLI/socket in the test runner")
    subprocess.run(["docker", "compose", "restart", "backend"], check=True, timeout=120)
    _wait_for_health()


def test_postgresql_authoritative_persistence_lifecycle(tmp_path: Path):
    """Verify durable sessions/documents while Redis cache and RAG data change."""
    _wait_for_health()
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=False)
    session = requests.Session()
    email = f"persistence_{uuid.uuid4().hex}@example.com"
    password = "PersistencePass123!"
    user_id = None
    tenant_id = None
    chat_id = None
    document_id = None
    try:
        signup = session.post(
            f"{BASE_URL}/api/auth/signup",
            json={"email": email, "password": password, "name": "Persistence Test"},
            timeout=10,
        )
        assert signup.status_code == 200, f"Signup failed: {signup.text}"
        signup_body = signup.json()
        assert "token" not in signup_body, "Session token must not be returned in JSON"
        user_id = signup_body["user"]["id"]
        tenant_id = signup_body["user"].get("tenant_id")

        # Explicit login to establish authenticated session
        login_res = session.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": password},
            timeout=10,
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        csrf = session.cookies.get("csrf_token")
        assert session.cookies.get("session_token"), "HttpOnly session cookie was not set on login"
        assert csrf, "CSRF cookie was not set on login"

        created = session.post(
            f"{BASE_URL}/api/sessions",
            json={"title": "Durable persistence test"},
            headers={"X-CSRF-Token": csrf},
            timeout=10,
        )
        assert created.status_code == 200, f"Chat creation failed: {created.text}"
        chat_id = created.json()["id"]
        db_chat = _db_one("SELECT id, user_id, tenant_id, title FROM chats WHERE session_key = %s", (chat_id,))
        assert db_chat and str(db_chat["user_id"]) == user_id and (not tenant_id or str(db_chat["tenant_id"]) == tenant_id)

        # Remove only this chat's Redis cache entries, never the shared database.
        redis_client.delete(f"session:{chat_id}", f"session:{chat_id}:messages")
        restored = session.get(f"{BASE_URL}/api/sessions/{chat_id}", timeout=10)
        assert restored.status_code == 200, f"Session was not restored from PostgreSQL: {restored.text}"
        assert restored.json()["session"]["id"] == chat_id
        assert redis_client.exists(f"session:{chat_id}"), "Durable session was not repopulated into Redis cache"

        pdf_path = tmp_path / "durable.pdf"
        pdf_path.write_bytes(_create_pdf())
        with pdf_path.open("rb") as pdf_file:
            uploaded = session.post(
                f"{BASE_URL}/api/documents/upload",
                data={"session_id": chat_id},
                files={"file": ("durable.pdf", pdf_file, "application/pdf")},
                headers={"X-CSRF-Token": csrf},
                timeout=120,
            )
        assert uploaded.status_code == 200, f"Document upload failed: {uploaded.text}"
        document = uploaded.json()
        document_id = document["id"]
        assert document["status"] == "READY", f"Document was not READY: {document}"

        db_document = _db_one(
            "SELECT id, user_id, tenant_id, session_id, status FROM documents WHERE id = %s",
            (document_id,),
        )
        assert db_document, "Document metadata was not persisted in PostgreSQL"
        assert str(db_document["user_id"]) == user_id
        assert str(db_document["tenant_id"]) == tenant_id
        assert db_document["session_id"] == chat_id
        assert db_document["status"] == "READY"

        question = session.post(
            f"{BASE_URL}/api/agent",
            data={"session_id": chat_id, "query": "What is the GPA in the document?", "model": "ollama/llama3.2:3b"},
            headers={"X-CSRF-Token": csrf},
            timeout=120,
        )
        assert question.status_code == 200, f"Authenticated PDF question failed: {question.text[:500]}"
        answer = _streamed_text(question)
        assert "9.1" in answer, f"Grounded PDF answer did not contain the indexed GPA: {answer[:500]}"

        chunk_keys = []
        for key in redis_client.scan_iter(match="chunk:*"):
            if redis_client.hget(key, "document_id") in (document_id, document_id.encode()):
                chunk_keys.append(key)
        assert chunk_keys, "PDF was not indexed into Redis RAG chunks"

        deleted = session.delete(
            f"{BASE_URL}/api/documents/{document_id}",
            headers={"X-CSRF-Token": csrf},
            timeout=20,
        )
        assert deleted.status_code == 200, f"Document deletion failed: {deleted.text}"
        assert session.get(f"{BASE_URL}/api/documents/{document_id}", timeout=10).status_code == 404
        assert _db_one("SELECT id FROM documents WHERE id = %s", (document_id,)) is None
        assert not any(
            redis_client.hget(key, "document_id") in (document_id, document_id.encode())
            for key in redis_client.scan_iter(match="chunk:*")
        ), "Deleted document left Redis RAG chunks behind"

        _optional_backend_restart()
        restored_after_restart = session.get(f"{BASE_URL}/api/sessions/{chat_id}", timeout=10)
        assert restored_after_restart.status_code == 200, "PostgreSQL session did not survive backend restart"
        assert restored_after_restart.json()["session"]["id"] == chat_id
    finally:
        if document_id:
            redis_client.delete(f"document:{document_id}")
        if chat_id:
            redis_client.delete(f"session:{chat_id}", f"session:{chat_id}:messages", f"session:{chat_id}:documents")
        _db_cleanup(user_id, tenant_id)
        redis_client.close()