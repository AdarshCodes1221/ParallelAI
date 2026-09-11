from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from core.redis_store import RedisStore
from core.postgres_store import PostgresStore
from core.config import get_settings


class SessionService:
    def __init__(self, store: RedisStore | None = None):
        self.store = store or RedisStore()
        self.db = PostgresStore() if store is None and get_settings().database_url else None

    def create(self, session_id: str | None = None, title: str = "New Chat", user_id: str = "default_user") -> dict[str, Any]:
        session_id = session_id or str(uuid.uuid4())
        if self.db:
            session = self.db.create_chat(session_id, user_id, title)
            if session is None:
                raise ValueError("user_not_found")
            self._cache(session)
            return session
        now = datetime.now(timezone.utc).isoformat()
        session = {
            "id": session_id,
            "user_id": user_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "summary": "",
        }
        self.store.hset_json(f"session:{session_id}", session)
        self.store.client.sadd("sessions:all", session_id)
        if user_id:
            self.store.client.sadd(f"user:{user_id}:sessions", session_id)
        return session

    def get(self, session_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        if self.db:
            session = self.db.get_chat(session_id, user_id)
            if session:
                self._cache(session)
            return session
        value = self.store.hgetall_json(f"session:{session_id}")
        if not value:
            return None
        # If user_id is specified, enforce ownership
        if user_id and value.get("user_id") and value.get("user_id") != user_id:
            return None
        return value

    def update(self, session_id: str, user_id: str | None = None, **fields: Any) -> dict[str, Any] | None:
        if self.db:
            session = self.db.update_chat(session_id, fields, user_id=user_id)
            if session:
                self._cache(session)
            return session
        session = self.store.hgetall_json(f"session:{session_id}")
        if not session:
            return None
        if user_id and session.get("user_id") and session.get("user_id") != user_id:
            return None
        session.update(fields)
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.store.hset_json(f"session:{session_id}", session)
        return session

    def list_all(self, limit: int = 50, user_id: str | None = None) -> list[dict[str, Any]]:
        if self.db:
            if not user_id:
                return []
            sessions = self.db.list_chats(user_id, limit)
            for session in sessions:
                self._cache(session)
            return sessions
        if user_id:
            raw_ids = self.store.client.smembers(f"user:{user_id}:sessions")
        else:
            raw_ids = self.store.client.smembers("sessions:all")

        ids = [doc_id.decode("utf-8") if isinstance(doc_id, bytes) else doc_id for doc_id in raw_ids]
        sessions = []
        for sid in ids:
            s = self.store.hgetall_json(f"session:{sid}")
            if s:
                if not user_id or s.get("user_id") == user_id or not s.get("user_id"):
                    sessions.append(s)
            else:
                if user_id:
                    self.store.client.srem(f"user:{user_id}:sessions", sid)
                self.store.client.srem("sessions:all", sid)
        sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return sessions[:limit]

    def require(self, session_id: str, user_id: str = "default_user") -> dict[str, Any]:
        session = self.get(session_id, user_id=user_id)
        if not session:
            session = self.create(session_id, user_id=user_id)
        return session

    def save_message(self, session_id: str, role: str, content: str, user_id: str = "default_user") -> None:
        self.require(session_id, user_id=user_id)
        now = datetime.now(timezone.utc).isoformat()
        if self.db:
            self.db.add_message(session_id, user_id, role, content)
            self.store.lpush_json(f"session:{session_id}:messages", {"role": role, "content": content, "created_at": now}, max_length=50)
            return
        self.store.lpush_json(
            f"session:{session_id}:messages",
            {"role": role, "content": content, "created_at": now},
            max_length=50
        )
        self.update(session_id, updated_at=now)

    def recent_messages(self, session_id: str, limit: int = 12, user_id: str | None = None) -> list[dict[str, Any]]:
        if self.db:
            messages = self.db.list_messages(session_id, user_id=user_id, limit=limit)
            self.store.delete(f"session:{session_id}:messages")
            for message in reversed(messages):
                self.store.lpush_json(f"session:{session_id}:messages", message, max_length=50)
            return messages
        return list(reversed(self.store.lrange_json(f"session:{session_id}:messages", 0, limit - 1)))

    def active_document_ids(self, session_id: str) -> list[str]:
        raw_ids = self.store.client.smembers(f"session:{session_id}:documents")
        return sorted(
            doc_id.decode("utf-8") if isinstance(doc_id, bytes) else doc_id
            for doc_id in raw_ids
        )

    def delete(self, session_id: str, user_id: str | None = None) -> bool:
        if self.db:
            if not user_id or not self.db.delete_chat(session_id, user_id):
                return False
            self.store.delete(f"session:{session_id}", f"session:{session_id}:messages", f"session:{session_id}:documents")
            return True
        session = self.get(session_id, user_id=user_id)
        if not session and user_id:
            return False
        uid = session.get("user_id") if session else user_id
        self.store.delete(
            f"session:{session_id}",
            f"session:{session_id}:messages",
            f"session:{session_id}:documents"
        )
        self.store.client.srem("sessions:all", session_id)
        if uid:
            self.store.client.srem(f"user:{uid}:sessions", session_id)
        return True

    def _cache(self, session: dict[str, Any]) -> None:
        self.store.hset_json(f"session:{session['id']}", session)
        self.store.client.sadd("sessions:all", session["id"])
        if session.get("user_id"):
            self.store.client.sadd(f"user:{session['user_id']}:sessions", session["id"])


