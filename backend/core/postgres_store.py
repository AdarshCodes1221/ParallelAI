from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - dependency is installed in production
    psycopg = None
    dict_row = None

from core.config import get_settings

logger = logging.getLogger(__name__)


class PostgresStore:
    """Durable SaaS identity and chat metadata store.

    Raw session and reset tokens never cross this boundary; only SHA-256
    digests are persisted.
    """

    def __init__(self, dsn: str | None = None):
        self.dsn = dsn or get_settings().database_url
        if not self.dsn:
            raise RuntimeError("DATABASE_URL is required for PostgreSQL-backed auth")
        if psycopg is None:
            raise RuntimeError("psycopg is required for PostgreSQL-backed auth")

    def _connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def ensure_schema(self) -> None:
        migration = Path(__file__).parent.parent / "migrations" / "001_saas_auth.sql"
        with self._connect() as conn:
            conn.execute(migration.read_text(encoding="utf-8"))

    @staticmethod
    def _safe_user(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result.pop("password_hash", None)

        for key in ("id", "tenant_id"):
            if result.get(key) is not None:
                result[key] = str(result[key])

        for key in ("created_at", "updated_at"):
            if result.get(key) is not None:
                result[key] = result[key].isoformat()

        return result

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE lower(email) = lower(%s)",
                (email,),
            ).fetchone()

        return self._safe_user(row) if row else None

    def get_user_credentials_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE lower(email) = lower(%s)",
                (email,),
            ).fetchone()

        return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = %s",
                (user_id,),
            ).fetchone()

        return self._safe_user(row) if row else None

    def create_user(
        self,
        email: str,
        password_hash: str,
        name: str,
    ) -> dict[str, Any]:
        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO tenants (id, name) VALUES (%s, %s)",
                    (tenant_id, f"{name}'s workspace"),
                )

                row = conn.execute(
                    """
                    INSERT INTO users
                        (id, tenant_id, email, name, password_hash)
                    VALUES
                        (%s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (user_id, tenant_id, email, name, password_hash),
                ).fetchone()

        except Exception as exc:
            if "unique" in str(exc).lower():
                raise ValueError("duplicate_email") from exc
            raise

        return self._safe_user(row)

    def update_password(self, user_id: str, password_hash: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET password_hash = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (password_hash, user_id),
            )

    def create_session(
        self,
        user_id: str,
        tenant_id: str,
        user_agent: str,
        ip_address: str,
        ttl: int,
    ) -> tuple[str, dict[str, Any]]:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl)

        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO sessions
                    (
                        user_id,
                        tenant_id,
                        token_hash,
                        user_agent,
                        ip_address,
                        expires_at
                    )
                VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s,
                        NULLIF(%s, '')::inet,
                        %s
                    )
                RETURNING id, created_at, expires_at
                """,
                (
                    user_id,
                    tenant_id,
                    self._token_hash(token),
                    user_agent[:200],
                    ip_address,
                    expires,
                ),
            ).fetchone()

        return token, {
            "session_id": str(row["id"]),
            "user_id": user_id,
            "tenant_id": tenant_id,
            "status": "active",
            "created_at": row["created_at"].isoformat(),
            "expires_at": row["expires_at"].isoformat(),
        }

    def get_session(self, token: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE sessions
                SET last_seen_at = now()
                WHERE token_hash = %s
                  AND revoked_at IS NULL
                  AND expires_at > now()
                RETURNING
                    id,
                    user_id,
                    tenant_id,
                    created_at,
                    expires_at
                """,
                (self._token_hash(token),),
            ).fetchone()

        if not row:
            return None

        return {
            "session_id": str(row["id"]),
            "user_id": str(row["user_id"]),
            "tenant_id": str(row["tenant_id"]),
            "status": "active",
            "created_at": row["created_at"].isoformat(),
            "expires_at": row["expires_at"].isoformat(),
        }

    def delete_session(self, identifier: str) -> bool:
        """Revoke/delete a session by raw session token or session UUID."""
        if not identifier:
            return False
        token_hash = self._token_hash(identifier)
        with self._connect() as conn:
            try:
                uuid_obj = uuid.UUID(identifier)
                row = conn.execute(
                    """
                    UPDATE sessions
                    SET revoked_at = now()
                    WHERE (id = %s OR token_hash = %s)
                      AND revoked_at IS NULL
                    RETURNING id
                    """,
                    (uuid_obj, token_hash),
                ).fetchone()
            except (ValueError, AttributeError):
                row = conn.execute(
                    """
                    UPDATE sessions
                    SET revoked_at = now()
                    WHERE token_hash = %s
                      AND revoked_at IS NULL
                    RETURNING id
                    """,
                    (token_hash,),
                ).fetchone()
            return bool(row)

    def delete_user_sessions(self, user_id: str) -> int:
        """Revoke/delete all active sessions belonging to user_id."""
        if not user_id:
            return 0
        with self._connect() as conn:
            rows = conn.execute(
                """
                UPDATE sessions
                SET revoked_at = now()
                WHERE user_id = %s
                  AND revoked_at IS NULL
                RETURNING id
                """,
                (user_id,),
            ).fetchall()
            return len(rows)

    def revoke_session(self, token: str) -> None:
        self.delete_session(token)

    def revoke_user_sessions(self, user_id: str) -> int:
        return self.delete_user_sessions(user_id)

    def create_reset_token(self, user_id: str, ttl: int) -> str:
        raw_token = secrets.token_urlsafe(32)

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE password_reset_tokens
                SET used_at = now()
                WHERE user_id = %s
                  AND used_at IS NULL
                """,
                (user_id,),
            )

            conn.execute(
                """
                INSERT INTO password_reset_tokens
                    (user_id, token_hash, expires_at)
                VALUES
                    (
                        %s,
                        %s,
                        now() + (%s * interval '1 second')
                    )
                """,
                (user_id, self._token_hash(raw_token), ttl),
            )

        return raw_token

    def consume_reset_token(self, token: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE password_reset_tokens
                SET used_at = now()
                WHERE token_hash = %s
                  AND used_at IS NULL
                  AND expires_at > now()
                RETURNING user_id
                """,
                (self._token_hash(token),),
            ).fetchone()

        return str(row["user_id"]) if row else None

    def audit(
        self,
        event_type: str,
        user_id: str | None = None,
        tenant_id: str | None = None,
        ip_address: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events
                    (
                        event_type,
                        user_id,
                        tenant_id,
                        ip_address,
                        metadata
                    )
                VALUES
                    (
                        %s,
                        %s,
                        %s,
                        NULLIF(%s, '')::inet,
                        %s
                    )
                """,
                (
                    event_type,
                    user_id,
                    tenant_id,
                    ip_address,
                    json.dumps(metadata or {}),
                ),
            )

    def user_tenant(self, user_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT tenant_id FROM users WHERE id = %s",
                (user_id,),
            ).fetchone()

        return str(row["tenant_id"]) if row else None

    @staticmethod
    def _iso(value: Any) -> str:
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    def create_chat(
        self,
        session_id: str,
        user_id: str,
        title: str,
    ) -> dict[str, Any] | None:
        tenant_id = self.user_tenant(user_id)

        if not tenant_id:
            return None

        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO chats
                    (
                        id,
                        session_key,
                        tenant_id,
                        user_id,
                        title
                    )
                VALUES
                    (
                        gen_random_uuid(),
                        %s,
                        %s,
                        %s,
                        %s
                    )
                RETURNING *
                """,
                (session_id, tenant_id, user_id, title),
            ).fetchone()

        return self._chat(row)

    @classmethod
    def _chat(cls, row: dict[str, Any]) -> dict[str, Any]:
        metadata = row.get("metadata") or {}

        return {
            "id": row.get("session_key") or str(row["id"]),
            "user_id": str(row["user_id"]),
            "tenant_id": str(row["tenant_id"]),
            "title": row["title"],
            "summary": metadata.get("summary", ""),
            "created_at": cls._iso(row["created_at"]),
            "updated_at": cls._iso(row["updated_at"]),
        }

    def get_chat(
        self,
        session_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        # FIX:
        # The ownership filter must reference the chats table itself.
        # There is no "m" alias in this query.
        query = """
            SELECT c.*
            FROM chats AS c
            WHERE (
                c.session_key = %s
                OR (
                    c.session_key = ''
                    AND c.id::text = %s
                )
            )
        """

        params: list[Any] = [session_id, session_id]

        if user_id:
            query += " AND c.user_id = %s"
            params.append(user_id)

        query += " LIMIT 1"

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()

        return self._chat(row) if row else None

    def update_chat(
        self,
        session_id: str,
        fields: dict[str, Any],
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        allowed = {"title"}
        updates = {
            key: value
            for key, value in fields.items()
            if key in allowed
        }

        if not updates:
            return self.get_chat(session_id, user_id=user_id)

        assignments = ", ".join(
            f"{key} = %s"
            for key in updates
        )

        params: list[Any] = list(updates.values())
        params.append(session_id)
        where_clause = "WHERE session_key = %s"

        if user_id:
            where_clause += " AND user_id = %s"
            params.append(user_id)

        with self._connect() as conn:
            conn.execute(
                f"""
                UPDATE chats
                SET {assignments},
                    updated_at = now()
                {where_clause}
                """,
                params,
            )

            select_params = [session_id] + ([user_id] if user_id else [])
            row = conn.execute(
                "SELECT * FROM chats " + where_clause,
                select_params,
            ).fetchone()

        return self._chat(row) if row else None

    def list_chats(
        self,
        user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM chats
                WHERE user_id = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()

        return [self._chat(row) for row in rows]

    def add_message(
        self,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
    ) -> None:
        chat = self.get_chat(session_id, user_id)

        if not chat:
            return

        with self._connect() as conn:
            chat_row = conn.execute(
                """
                SELECT id, tenant_id
                FROM chats
                WHERE session_key = %s
                  AND user_id = %s
                """,
                (session_id, user_id),
            ).fetchone()

            if not chat_row:
                return

            conn.execute(
                """
                INSERT INTO messages
                    (
                        chat_id,
                        tenant_id,
                        user_id,
                        role,
                        content
                    )
                VALUES
                    (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                """,
                (
                    chat_row["id"],
                    chat_row["tenant_id"],
                    user_id,
                    role,
                    content,
                ),
            )

            conn.execute(
                """
                UPDATE chats
                SET updated_at = now()
                WHERE id = %s
                """,
                (chat_row["id"],),
            )

    def list_messages(
        self,
        session_id: str,
        user_id: str | None = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT
                m.role,
                m.content,
                m.created_at
            FROM messages AS m
            JOIN chats AS c
              ON c.id = m.chat_id
            WHERE (
                c.session_key = %s
                OR c.id::text = %s
            )
        """

        params: list[Any] = [session_id, session_id]

        if user_id:
            query += " AND c.user_id = %s"
            params.append(user_id)

        query += """
            ORDER BY m.created_at DESC
            LIMIT %s
        """
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "role": row["role"],
                "content": row["content"],
                "created_at": self._iso(row["created_at"]),
            }
            for row in reversed(rows)
        ]

    def delete_chat(
        self,
        session_id: str,
        user_id: str,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                DELETE FROM chats
                WHERE session_key = %s
                  AND user_id = %s
                RETURNING id
                """,
                (session_id, user_id),
            ).fetchone()

        return bool(row)

    @classmethod
    def _document(cls, row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row.get("metadata") or {})

        result.update(
            {
                "id": str(row["id"]),
                "session_id": row["session_id"],
                "user_id": str(row["user_id"]),
                "tenant_id": str(row["tenant_id"]),
                "filename": row["filename"],
                "object_key": result.get("object_key", ""),
                "checksum": row["checksum"],
                "mime_type": row["mime_type"],
                "status": row["status"],
                "created_at": cls._iso(row["created_at"]),
                "updated_at": cls._iso(row["updated_at"]),
            }
        )

        return result

    def create_document(
        self,
        document: dict[str, Any],
    ) -> dict[str, Any] | None:
        tenant_id = self.user_tenant(document["user_id"])

        if not tenant_id:
            return None

        raw_doc_id = document.get("id")
        try:
            doc_uuid = uuid.UUID(str(raw_doc_id))
        except (ValueError, AttributeError):
            doc_uuid = uuid.uuid5(uuid.NAMESPACE_URL, str(raw_doc_id)) if raw_doc_id else uuid.uuid4()
            document["id"] = str(doc_uuid)

        metadata = {
            key: value
            for key, value in document.items()
            if key not in {
                "id",
                "session_id",
                "user_id",
                "tenant_id",
                "filename",
                "checksum",
                "mime_type",
                "status",
                "created_at",
                "updated_at",
            }
        }

        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO documents
                    (
                        id,
                        tenant_id,
                        user_id,
                        chat_id,
                        session_id,
                        filename,
                        object_key,
                        checksum,
                        mime_type,
                        status,
                        metadata
                    )
                VALUES
                    (
                        %s,
                        %s,
                        %s,
                        NULLIF(%s, '')::uuid,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                ON CONFLICT (id) DO UPDATE SET
                    updated_at = now(),
                    status = EXCLUDED.status,
                    session_id = EXCLUDED.session_id,
                    metadata = EXCLUDED.metadata
                RETURNING *
                """,
                (
                    document["id"],
                    tenant_id,
                    document["user_id"],
                    None,
                    document["session_id"],
                    document["filename"],
                    document.get("object_key", ""),
                    document["checksum"],
                    document["mime_type"],
                    document["status"],
                    json.dumps(metadata),
                ),
            ).fetchone()

        return self._document(row)

    @staticmethod
    def _safe_doc_uuid(document_id: str) -> str:
        if not document_id:
            return ""
        try:
            return str(uuid.UUID(str(document_id)))
        except (ValueError, AttributeError):
            return str(uuid.uuid5(uuid.NAMESPACE_URL, str(document_id)))

    def get_document(
        self,
        document_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        clean_id = self._safe_doc_uuid(document_id)
        if not clean_id:
            return None

        query = """
            SELECT *
            FROM documents
            WHERE id = %s
        """
        params: list[Any] = [clean_id]

        if user_id:
            query += " AND user_id = %s"
            params.append(user_id)

        query += " LIMIT 1"

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()

        return self._document(row) if row else None

    def update_document(
        self,
        document_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any] | None:
        clean_id = self._safe_doc_uuid(document_id)
        if not clean_id:
            return None

        document = self.get_document(clean_id)

        if not document:
            return None

        metadata = {
            key: value
            for key, value in fields.items()
            if key not in {"status"}
        }

        assignments = ["updated_at = now()"]
        params: list[Any] = []

        if "status" in fields:
            assignments.append("status = %s")
            params.append(fields["status"])

        if metadata:
            assignments.append("metadata = metadata || %s::jsonb")
            params.append(json.dumps(metadata))

        params.append(clean_id)

        with self._connect() as conn:
            row = conn.execute(
                f"""
                UPDATE documents
                SET {", ".join(assignments)}
                WHERE id = %s
                RETURNING *
                """,
                params,
            ).fetchone()

        return self._document(row) if row else None

    def list_documents(
        self,
        session_id: str | None,
        user_id: str,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT *
            FROM documents
            WHERE user_id = %s
        """
        params: list[Any] = [user_id]

        if session_id:
            query += " AND session_id = %s"
            params.append(session_id)

        query += " ORDER BY created_at DESC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        return [self._document(row) for row in rows]

    def delete_document(
        self,
        document_id: str,
        user_id: str | None = None,
    ) -> bool:
        clean_id = self._safe_doc_uuid(document_id)
        if not clean_id:
            return False

        query = """
            DELETE FROM documents
            WHERE id = %s
        """
        params: list[Any] = [clean_id]

        if user_id:
            query += " AND user_id = %s"
            params.append(user_id)

        query += " RETURNING id"

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()

        return bool(row)