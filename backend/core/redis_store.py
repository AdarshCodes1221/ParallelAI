import json
import logging
from typing import Any

import redis

from core.config import get_settings

logger = logging.getLogger(__name__)


class RedisStore:
    """Small Redis boundary used by sessions, documents, and RAG repositories."""

    def __init__(self, url: str | None = None):
        self.url = url or get_settings().redis_url
        # decode_responses=False so binary vector embeddings (struct.pack bytes)
        # survive hset/hget and FT.SEARCH without UnicodeDecodeError.
        self.client = redis.Redis.from_url(self.url, decode_responses=False)

    @staticmethod
    def _to_str(value: Any) -> str:
        """Decode bytes to str; pass through str/int unchanged."""
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    def ping(self) -> bool:
        return bool(self.client.ping())

    def set_json(self, key: str, value: Any, *, ex: int | None = None) -> None:
        self.client.set(key, json.dumps(value, ensure_ascii=True), ex=ex)

    def get_json(self, key: str) -> Any | None:
        value = self.client.get(key)
        if value is None:
            return None
        return json.loads(self._to_str(value))

    def hset_json(self, key: str, mapping: dict[str, Any]) -> None:
        self.client.hset(key, mapping={name: json.dumps(val, ensure_ascii=True) if isinstance(val, (dict, list)) else str(val) for name, val in mapping.items()})

    def hgetall_json(self, key: str) -> dict[str, Any]:
        values = self.client.hgetall(key)
        result: dict[str, Any] = {}
        for name, value in values.items():
            name_str = self._to_str(name)
            try:
                result[name_str] = json.loads(self._to_str(value))
            except (TypeError, json.JSONDecodeError):
                result[name_str] = self._to_str(value)
        return result

    def delete(self, *keys: str) -> int:
        return int(self.client.delete(*keys))

    def lpush_json(self, key: str, value: Any, *, max_length: int | None = None) -> None:
        pipe = self.client.pipeline()
        pipe.lpush(key, json.dumps(value, ensure_ascii=True))
        if max_length:
            pipe.ltrim(key, 0, max_length - 1)
        pipe.execute()

    def lrange_json(self, key: str, start: int = 0, end: int = -1) -> list[Any]:
        values = self.client.lrange(key, start, end)
        return [json.loads(self._to_str(value)) for value in values]
