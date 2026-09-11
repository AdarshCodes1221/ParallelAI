from __future__ import annotations

import hashlib
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import get_settings
from core.redis_store import RedisStore
from services.object_storage import ObjectStorage
from core.postgres_store import PostgresStore


class DocumentService:
    def __init__(self, store: RedisStore | None = None):
        self.store = store or RedisStore()
        self.root = Path(get_settings().document_storage_path)
        self.root.mkdir(parents=True, exist_ok=True)
        self.object_storage = ObjectStorage()
        self.db = PostgresStore() if store is None and get_settings().database_url else None

    def create_from_bytes(self, filename: str, content: bytes, session_id: str, mime_type: str | None = None, user_id: str = "default_user") -> dict[str, Any]:
        checksum = hashlib.sha256(content).hexdigest()
        duplicate_id = self.store.client.get(f"document:checksum:{session_id}:{checksum}")
        if duplicate_id:
            if isinstance(duplicate_id, bytes):
                duplicate_id = duplicate_id.decode("utf-8")
            existing = self.get(duplicate_id, user_id=user_id)
            if existing:
                return existing | {"duplicate": True}
        document_id = str(uuid.uuid4())
        safe_name = Path(filename or "upload").name or "upload"
        storage_path = self.root / document_id / safe_name
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(content)
        now = datetime.now(timezone.utc).isoformat()
        detected_mime = mime_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        object_key = f"{user_id}/{document_id}/{safe_name}"
        self.object_storage.put(object_key, content, detected_mime)
        modality = "pdf" if detected_mime == "application/pdf" else ("image" if detected_mime.startswith("image/") else ("audio" if detected_mime.startswith(("audio/", "video/")) else "text"))
        document = {
            "id": document_id,
            "session_id": session_id,
            "user_id": user_id,
            "filename": safe_name,
            "mime_type": detected_mime,
            "storage_path": str(storage_path),
            "object_key": object_key if self.object_storage.enabled else "",
            "checksum": checksum,
            "size": len(content),
            "status": "UPLOADED",
            "extracted_text": "",
            "confidence": 1.0,
            "modality": modality,
            "source_type": modality,
            "language": "auto",
            "page_count": 0,
            "chunk_count": 0,
            "duration_seconds": 0,
            "created_at": now,
            "updated_at": now,
        }
        if self.db:
            durable = self.db.create_document(document)
            if durable is None:
                raise ValueError("user_not_found")
            document = durable
        self.store.hset_json(f"document:{document_id}", document)
        self.store.client.set(f"document:checksum:{session_id}:{checksum}", document_id)
        self.store.client.sadd(f"session:{session_id}:documents", document_id)
        self.store.client.sadd("documents:all", document_id)
        if user_id:
            self.store.client.sadd(f"user:{user_id}:documents", document_id)
        return document

    def create_text_document(
        self,
        filename: str,
        text: str,
        session_id: str,
        modality: str = "youtube",
        mime_type: str = "text/plain",
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta = metadata or {}
        raw_doc_id = meta.get("document_id")
        try:
            document_id = str(uuid.UUID(str(raw_doc_id))) if raw_doc_id else str(uuid.uuid4())
        except (ValueError, AttributeError):
            document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(raw_doc_id))) if raw_doc_id else str(uuid.uuid4())
            meta["custom_document_id"] = raw_doc_id
        now = datetime.now(timezone.utc).isoformat()
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        uid = meta.get("user_id", "default_user")
        document = {
            "id": document_id,
            "session_id": session_id,
            "user_id": uid,
            "filename": filename,
            "mime_type": mime_type,
            "storage_path": "",
            "checksum": checksum,
            "size": len(text.encode("utf-8")),
            "status": "READY",
            "extracted_text": text,
            "confidence": confidence,
            "modality": modality,
            "source_type": meta.get("source_type", modality),
            "video_id": meta.get("video_id") or meta.get("youtube_video_id", ""),
            "youtube_video_id": meta.get("youtube_video_id") or meta.get("video_id", ""),
            "source_url": meta.get("source_url") or meta.get("url", ""),
            "url": meta.get("url") or meta.get("source_url", ""),
            "title": meta.get("title", filename),
            "transcript_available": meta.get("transcript_available", True),
            "language": meta.get("language", "auto"),
            "page_count": meta.get("page_count", 0),
            "chunk_count": meta.get("chunk_count", 0),
            "duration_seconds": meta.get("duration_seconds", 0),
            "created_at": now,
            "updated_at": now,
        }
        if self.db:
            durable = self.db.create_document(document)
            if durable is None:
                raise ValueError("user_not_found")
            document = durable
        self.store.hset_json(f"document:{document_id}", document)
        self.store.client.sadd(f"session:{session_id}:documents", document_id)
        self.store.client.sadd("documents:all", document_id)
        if uid:
            self.store.client.sadd(f"user:{uid}:documents", document_id)
        return document

    def get(self, document_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        try:
            clean_id = str(uuid.UUID(str(document_id)))
        except (ValueError, AttributeError):
            clean_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(document_id))) if document_id else ""
        lookup_id = clean_id or document_id
        if self.db:
            document = self.db.get_document(lookup_id, user_id)
            if document:
                self.store.hset_json(f"document:{document['id']}", document)
            return document
        value = self.store.hgetall_json(f"document:{lookup_id}")
        if not value:
            return None
        if user_id and value.get("user_id") and value.get("user_id") != user_id:
            return None
        return value

    def update(self, document_id: str, **fields: Any) -> dict[str, Any] | None:
        try:
            clean_id = str(uuid.UUID(str(document_id)))
        except (ValueError, AttributeError):
            clean_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(document_id))) if document_id else ""
        lookup_id = clean_id or document_id
        if self.db:
            document = self.db.update_document(lookup_id, fields)
            if document:
                self.store.hset_json(f"document:{document['id']}", document)
            return document
        document = self.store.hgetall_json(f"document:{lookup_id}")
        if not document:
            return None
        document.update(fields)
        document["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.store.hset_json(f"document:{lookup_id}", document)
        return document

    def list(self, session_id: str | None = None, user_id: str | None = None) -> list[dict[str, Any]]:
        if self.db:
            if not user_id:
                return []
            documents = self.db.list_documents(session_id, user_id)
            for document in documents:
                self.store.hset_json(f"document:{document['id']}", document)
            return documents
        if session_id:
            raw_ids = self.store.client.smembers(f"session:{session_id}:documents")
        elif user_id:
            raw_ids = self.store.client.smembers(f"user:{user_id}:documents")
        else:
            raw_ids = self.store.client.smembers("documents:all")

        ids = [doc_id.decode("utf-8") if isinstance(doc_id, bytes) else doc_id for doc_id in raw_ids]
        docs = []
        for document_id in ids:
            d = self.get(document_id, user_id=user_id)
            if d:
                docs.append(d)
        docs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return docs

    def list_for_session(self, session_id: str, user_id: str | None = None) -> list[dict[str, Any]]:
        return self.list(session_id=session_id, user_id=user_id)

    def delete(self, document_id: str, user_id: str | None = None) -> bool:
        if self.db:
            document = self.db.get_document(document_id, user_id)
            if not document:
                return False
            self._delete_external_data(document)
            if not self.db.delete_document(document_id, user_id):
                return False
            self._remove_cache_memberships(document)
            return True
        document = self.get(document_id, user_id=user_id)
        if not document and user_id:
            return False
        if not document:
            return False
        uid = document.get("user_id")
        try:
            if document.get("object_key"):
                self.object_storage.delete(document["object_key"])
            if document.get("storage_path"):
                Path(document["storage_path"]).unlink(missing_ok=True)
                Path(document["storage_path"]).parent.rmdir()
        except OSError:
            pass
        # Redis is the RAG index, so remove every chunk owned by this document.
        for key in self.store.client.scan_iter(match="chunk:*"):
            chunk_key = key.decode("utf-8") if isinstance(key, bytes) else key
            if self.store.client.hget(chunk_key, "document_id") in (document_id, document_id.encode()):
                self.store.client.delete(chunk_key)
        self.store.delete(f"document:{document_id}")
        self.store.client.srem("documents:all", document_id)
        if uid:
            self.store.client.srem(f"user:{uid}:documents", document_id)
        if document.get("session_id"):
            self.store.client.srem(f"session:{document['session_id']}:documents", document_id)
        return True

    def _delete_external_data(self, document: dict[str, Any]) -> None:
        try:
            if document.get("object_key"):
                self.object_storage.delete(document["object_key"])
            if document.get("storage_path"):
                Path(document["storage_path"]).unlink(missing_ok=True)
                Path(document["storage_path"]).parent.rmdir()
        except OSError:
            pass
        for key in self.store.client.scan_iter(match="chunk:*"):
            chunk_key = key.decode("utf-8") if isinstance(key, bytes) else key
            if self.store.client.hget(chunk_key, "document_id") in (document["id"], document["id"].encode()):
                self.store.client.delete(chunk_key)

    def _remove_cache_memberships(self, document: dict[str, Any]) -> None:
        self.store.delete(f"document:{document['id']}")
        self.store.client.srem("documents:all", document["id"])
        self.store.client.srem(f"user:{document.get('user_id')}:documents", document["id"])
        self.store.client.srem(f"session:{document.get('session_id')}:documents", document["id"])

