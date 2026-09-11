import hashlib
import logging
import re
from typing import Sequence

from core.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    pass


class EmbeddingService:
    """Provider-independent embedding boundary.

    Resolution order:
      1. Remote (Gemini ``text-embedding-004`` / ``gemini-embedding-2``) when
         an ``api_key`` is supplied and succeeds.
      2. Ollama ``nomic-embed-text`` when no api key is configured (local LLM
         fallback) — real semantic embeddings without any external API.
      3. Deterministic hash-based embedding when Ollama is also unavailable,
         so RAG can always index and search, even if purely structurally.

    The dimension is fixed at the configured value (default 768) so the
    Redis ``HNSW`` index and every embedding provider agree.
    """

    _LOCAL_SEED = 0xC0FFEE  # deterministic seed for hash fallback
    _CACHE_MAX_SIZE = 512
    _QUERY_CACHE: dict[tuple[str, str, int], list[float]] = {}

    def __init__(self, api_key: str | None = None, model: str | None = None, dimension: int | None = None):
        self.api_key = api_key or None
        settings = get_settings()
        self.provider = settings.embedding_provider.lower()
        self.model = model or settings.embedding_model
        self.dimension = dimension or settings.embedding_dimension
        if self.dimension is None:
            self.dimension = 768
        self._ollama_url = settings.ollama_url
        # Decide which local backend to prefer
        self._provider = "remote" if self.api_key else "local"

    # ── Ollama local embeddings ───────────────────────────────────

    def _ollama_embed(self, texts: Sequence[str]) -> list[list[float]] | None:
        """Call Ollama's embedding API. Returns None if Ollama is unavailable."""
        import urllib.request
        import urllib.error
        import json as _json

        payload = _json.dumps({"model": self.model, "input": list(texts)}).encode("utf-8")
        req = urllib.request.Request(
            f"{self._ollama_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.URLError:
            return None
        # Ollama returns {"embeddings": [[...], ...]}
        try:
            data = _json.loads(raw)
        except _json.JSONDecodeError:
            return None
        embeddings = data.get("embeddings")
        if not embeddings or not isinstance(embeddings, list):
            return None
        vectors: list[list[float]] = []
        for emb in embeddings:
            if isinstance(emb, list):
                vec = [float(v) for v in emb]
            elif isinstance(emb, dict):
                vec = [float(v) for v in emb.get("embedding", [])]
            else:
                return None
            vectors.append(vec)
        if len(vectors) != len(texts):
            return None
        # Normalise to the configured dimension
        return self._coerce_dimension(vectors)

    # ── Local hash-based fallback ───────────────────────────────────

    def _local_embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Pure-Python deterministic embedding using token-hash → vector.

        Not semantically meaningful but produces consistent, normalised
        vectors of fixed dimension — enough for KNN retrieval when no local
        LLM is available either.
        """
        rng = __import__("random").Random(self._LOCAL_SEED)
        _weights = [[rng.uniform(-1, 1) for _ in range(self.dimension)]
                    for _ in range(256)]
        vectors: list[list[float]] = []
        for text in texts:
            tokens = re.findall(r"[a-z0-9]+", text.lower())
            if not tokens:
                tokens = ["<empty>"]
            vector = [0.0] * self.dimension
            for token in tokens:
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                for i in range(self.dimension):
                    byte_val = digest[i % len(digest)]
                    vector[i] += _weights[byte_val][i]
            norm = sum(v * v for v in vector) ** 0.5
            if norm > 0:
                vector = [v / norm for v in vector]
            vectors.append(vector)
        return vectors

    @staticmethod
    def _coerce_dimension(vectors: list[list[float]], target: int | None = None) -> list[list[float]]:
        """Truncate or zero-pad vectors to the configured/target dimension."""
        if target is None:
            target = get_settings().embedding_dimension or 768
        result = []
        for vec in vectors:
            if len(vec) == target:
                result.append(vec)
            elif len(vec) > target:
                result.append(vec[:target])
            else:
                result.append(vec + [0.0] * (target - len(vec)))
        return result

    # ── Public API ─────────────────────────────────────────────────

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        # Fast cache lookup
        cached_results: dict[int, list[float]] = {}
        missing_indices: list[int] = []
        missing_texts: list[str] = []

        for idx, text in enumerate(texts):
            cache_key = (text.strip(), self.model, self.dimension)
            if cache_key in self._QUERY_CACHE:
                cached_results[idx] = self._QUERY_CACHE[cache_key]
            else:
                missing_indices.append(idx)
                missing_texts.append(text)

        if not missing_texts:
            return [cached_results[i] for i in range(len(texts))]

        # 1. Cloud embeddings (opt-in)
        computed_vectors = None
        if self.api_key and self.provider in {"gemini", "remote", "cloud"}:
            try:
                computed_vectors = self._remote_embed(missing_texts)
            except EmbeddingError:
                raise
            except Exception as exc:
                logger.warning("Remote embedding failed, falling back to local: %s", exc)

        # 2. Ollama local embeddings
        if computed_vectors is None:
            computed_vectors = self._ollama_embed(missing_texts)
            if computed_vectors is not None:
                logger.info("embedding_response provider=ollama model=%s requested=%d returned=%d",
                            self.model, len(missing_texts), len(computed_vectors))

        # 3. Hash-based fallback
        if computed_vectors is None:
            logger.info("Using hash-based local embedding fallback (dimension=%d)", self.dimension)
            computed_vectors = self._local_embed(missing_texts)

        # Store in cache
        for missing_idx, text, vec in zip(missing_indices, missing_texts, computed_vectors):
            cache_key = (text.strip(), self.model, self.dimension)
            if len(self._QUERY_CACHE) >= self._CACHE_MAX_SIZE:
                # Evict oldest 20%
                for k in list(self._QUERY_CACHE.keys())[:int(self._CACHE_MAX_SIZE * 0.2)]:
                    self._QUERY_CACHE.pop(k, None)
            self._QUERY_CACHE[cache_key] = vec
            cached_results[missing_idx] = vec

        return [cached_results[i] for i in range(len(texts))]

    def _remote_embed(self, texts: Sequence[str]) -> list[list[float]]:
        from google import genai
        client = genai.Client(api_key=self.api_key)
        config = {"output_dimensionality": self.dimension} if self.dimension else None
        response = client.models.embed_content(model=self.model, contents=list(texts), config=config)
        embeddings = getattr(response, "embeddings", None) or []
        if not embeddings:
            single_embedding = getattr(response, "embedding", None)
            if single_embedding is not None:
                embeddings = [single_embedding]
        logger.info("embedding_response model=%s requested=%d returned=%d", self.model, len(texts), len(embeddings))
        if len(embeddings) != len(texts) and len(texts) > 1:
            logger.warning("embedding_batch_incomplete requested=%d returned=%d; retrying per text", len(texts), len(embeddings))
            embeddings = []
            for text in texts:
                item_response = client.models.embed_content(model=self.model, contents=text, config=config)
                item = getattr(item_response, "embedding", None)
                if item is None:
                    item_list = getattr(item_response, "embeddings", None) or []
                    item = item_list[0] if item_list else None
                if item is None:
                    raise EmbeddingError("Embedding provider returned an incomplete response")
                embeddings.append(item)
        vectors = [list(getattr(item, "values", item)) for item in embeddings]
        if len(vectors) != len(texts) or any(not vector for vector in vectors):
            raise EmbeddingError("Embedding provider returned an incomplete response")
        # Coerce to the configured dimension so local + remote vectors are interchangeable
        vectors = self._coerce_dimension(vectors, self.dimension)
        if self.dimension is None:
            self.dimension = len(vectors[0])
        return vectors
