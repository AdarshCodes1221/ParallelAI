"""Persistent Redis Stack hybrid retrieval for backwards-compatible callers."""

import hashlib
import json
import logging
import re
import struct
import time
import uuid
from typing import Any

from core.config import get_settings
from core.redis_store import RedisStore
from schemas.evidence import EvidenceDocument
from services.embedding_service import EmbeddingService
from services.retrieval.query_expander import generate_variants, retrieval_terms

logger = logging.getLogger(__name__)


class RAGService:
    """Persistent Redis Stack hybrid retrieval for backwards-compatible callers."""

    INDEX_NAME = "idx:chunks"
    PREFIX = "chunk:"

    @staticmethod
    def _escape_tag(value: str) -> str:
        """Escape special characters for Redis TAG filter syntax."""
        return re.sub(
            r"([,.<>{}\[\]\"':;!@#$%^&*()\-+=~| ])",
            r"\\\1",
            value,
        )

    @staticmethod
    def _decode(value: Any) -> Any:
        """Decode bytes to str; pass through everything else."""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    @staticmethod
    def _norm_key(value: Any) -> str:
        """Decode bytes keys to str for dict lookups."""
        return (
            value.decode("utf-8", errors="replace")
            if isinstance(value, bytes)
            else value
        )

    @classmethod
    def _parse_search_results(
        cls,
        raw: Any,
    ) -> list[dict[str, Any]]:
        if not raw:
            return []

        # Case 1: Redis returns a dictionary
        # e.g. {b"results": [...], b"total_results": N}
        if isinstance(raw, dict):
            results = (
                raw.get("results")
                or raw.get(b"results")
                or []
            )

            if isinstance(results, (list, tuple)):
                parsed = []

                for item in results:
                    if not isinstance(item, dict):
                        continue

                    fields = {
                        cls._norm_key(k): v
                        for k, v in item.items()
                    }

                    extra = fields.get("extra_attributes")

                    if isinstance(extra, dict):
                        fields.update(
                            {
                                cls._norm_key(k): v
                                for k, v in extra.items()
                            }
                        )

                    payload = fields.get("payload")

                    if isinstance(payload, dict):
                        fields.update(
                            {
                                cls._norm_key(k): v
                                for k, v in payload.items()
                            }
                        )

                    for internal_key in (
                        "id_raw",
                        "values",
                        "extra_attributes",
                        "payload",
                    ):
                        fields.pop(internal_key, None)

                    if fields:
                        decoded = {
                            cls._norm_key(k): cls._decode(v)
                            for k, v in fields.items()
                        }

                        if "id" not in decoded or not decoded["id"]:
                            decoded["id"] = decoded.get(
                                "id_raw",
                                "",
                            )

                        parsed.append(decoded)

                return parsed

        # Case 2: Redis returns a flat list
        # [count, key1, [f1, v1, ...], key2, ...]
        if isinstance(raw, (list, tuple)):
            if len(raw) < 2:
                return []

            first = cls._decode(raw[0])

            count = (
                int(first)
                if isinstance(first, (int, str))
                and str(first).isdigit()
                else 0
            )

            parsed = []

            for offset in range(
                1,
                min(
                    len(raw),
                    1 + count * 2,
                ),
                2,
            ):
                if (
                    offset + 1 >= len(raw)
                    or not isinstance(
                        raw[offset + 1],
                        (list, tuple),
                    )
                ):
                    continue

                doc_key = cls._decode(
                    raw[offset]
                )

                field_values = [
                    cls._decode(fv)
                    for fv in raw[offset + 1]
                ]

                item = dict(
                    zip(
                        field_values[::2],
                        field_values[1::2],
                    )
                )

                if "id" not in item or not item["id"]:
                    item["id"] = doc_key

                parsed.append(item)

            return parsed

        return []

    def __init__(
        self,
        api_key: str,
        redis_store: RedisStore | None = None,
    ):
        self.store = redis_store or RedisStore()
        self.embedder = EmbeddingService(
            api_key if api_key else None
        )
        self._ensure_index()

    def _ensure_index(
        self,
        dimension: int | None = None,
    ) -> None:
        configured_dimension = (
            dimension
            or get_settings().embedding_dimension
            or self.embedder.dimension
        )

        if not configured_dimension:
            logger.warning(
                "Redis chunk index will be created "
                "after the first embedding response"
            )
            return

        try:
            info = self.store.client.execute_command(
                "FT.INFO",
                self.INDEX_NAME,
            )

            existing_dim = self._extract_vector_dim(info)

            if existing_dim is not None:
                self.embedder.dimension = existing_dim
                return

        except Exception:
            # Index doesn't exist — create it.
            self._create_index(
                configured_dimension
            )

    @staticmethod
    def _extract_vector_dim(
        info: Any,
    ) -> int | None:
        """Pull the FLOAT32 vector dimension out of FT.INFO."""
        if isinstance(info, dict):
            attrs = (
                info.get("attributes")
                or info.get(b"attributes")
                or []
            )

            for attr in attrs:
                attr_dict = (
                    attr
                    if isinstance(attr, dict)
                    else {}
                )

                attr_type = (
                    attr_dict.get("type")
                    or attr_dict.get(b"type")
                )

                if attr_type in (
                    "VECTOR",
                    b"VECTOR",
                ):
                    dim = (
                        attr_dict.get("dim")
                        or attr_dict.get(b"dim")
                    )

                    if dim is not None:
                        try:
                            return int(dim)
                        except (
                            TypeError,
                            ValueError,
                        ):
                            pass

        elif isinstance(
            info,
            (list, tuple),
        ):
            for i, item in enumerate(info):
                if (
                    item == "dim"
                    or item == b"dim"
                ) and i + 1 < len(info):
                    try:
                        return int(info[i + 1])
                    except (
                        TypeError,
                        ValueError,
                    ):
                        pass

        return None

    def _drop_index(self) -> None:
        try:
            self.store.client.execute_command(
                "FT.DROPINDEX",
                self.INDEX_NAME,
            )

        except Exception as exc:
            logger.warning(
                "Failed to drop stale index: %s",
                exc,
            )

            # Try deleting individual chunk keys as fallback.
            try:
                keys = self.store.client.keys(
                    f"{self.PREFIX}*"
                )

                if keys:
                    self.store.client.delete(*keys)

            except Exception:
                logger.debug(
                    "Failed to delete individual "
                    "chunk keys as fallback"
                )

    def _create_index(
        self,
        dimension: int,
    ) -> None:
        try:
            self.store.client.execute_command(
                "FT.CREATE",
                self.INDEX_NAME,
                "ON",
                "HASH",
                "PREFIX",
                "1",
                self.PREFIX,
                "SCHEMA",
                "text",
                "TEXT",
                "session_id",
                "TAG",
                "document_id",
                "TAG",
                "source_type",
                "TAG",
                "user_id",
                "TAG",
                "page",
                "NUMERIC",
                "embedding",
                "VECTOR",
                "HNSW",
                "6",
                "TYPE",
                "FLOAT32",
                "DIM",
                str(dimension),
                "DISTANCE_METRIC",
                "COSINE",
            )

        except Exception as exc:
            logger.warning(
                "Unable to create Redis Search index: %s",
                exc,
            )

    @staticmethod
    def _chunks(
        text: str,
        size: int = 350,
        overlap: int = 60,
    ) -> list[str]:
        words = text.split()

        if not words:
            return []

        chunks = []

        step = max(
            1,
            size - overlap,
        )

        for start in range(
            0,
            len(words),
            step,
        ):
            chunk = " ".join(
                words[
                    start : start + size
                ]
            )

            if chunk:
                chunks.append(chunk)

            if start + size >= len(words):
                break

        return chunks

    def delete_document_chunks(self, document_id: str) -> int:
        count = 0
        try:
            for key in self.store.client.scan_iter(match="chunk:*"):
                val = self.store.client.hget(key, "document_id")
                if val in (document_id, document_id.encode()):
                    self.store.client.delete(key)
                    count += 1
        except Exception as e:
            logger.warning("Error deleting document chunks for %s: %s", document_id, e)
        return count

    def ingest_document(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        evidence: EvidenceDocument | None = None,
    ) -> list[str]:
        metadata = metadata or {}
        doc_id = metadata.get("document_id")
        if doc_id and doc_id != "legacy":
            self.delete_document_chunks(str(doc_id))

        block_chunks: list[
            tuple[str, dict[str, Any]]
        ] = []

        if evidence and evidence.blocks:
            for block in evidence.blocks:
                for chunk in self._chunks(
                    block.text
                ):
                    block_chunks.append(
                        (
                            chunk,
                            {
                                "page": block.page or 0,
                                "section": (
                                    block.section
                                    or ""
                                ),
                                "timestamp_start": (
                                    block.timestamp_start
                                ),
                                "timestamp_end": (
                                    block.timestamp_end
                                ),
                                "line_start": (
                                    block.line_start
                                ),
                                "line_end": (
                                    block.line_end
                                ),
                                "modality": (
                                    block.modality
                                ),
                                "verified_links": (
                                    block.metadata.get(
                                        "verified_links",
                                        [],
                                    )
                                ),
                            },
                        )
                    )
        else:
            block_chunks = [
                (chunk, {})
                for chunk in self._chunks(text)
            ]

        if not block_chunks:
            return []

        # Deduplicate chunks within the same document.
        doc_id = metadata.get(
            "document_id",
            "legacy",
        )

        seen_texts: set[str] = set()
        unique_chunks: list[
            tuple[str, dict[str, Any]]
        ] = []

        for chunk_text, chunk_meta in block_chunks:
            text_key = chunk_text.strip().lower()

            if text_key not in seen_texts:
                seen_texts.add(text_key)
                unique_chunks.append(
                    (
                        chunk_text,
                        chunk_meta,
                    )
                )

        if len(unique_chunks) < len(
            block_chunks
        ):
            logger.info(
                "Deduplicated %d → %d chunks "
                "for document %s",
                len(block_chunks),
                len(unique_chunks),
                doc_id,
            )

        block_chunks = unique_chunks

        vectors = self.embedder.embed(
            [
                chunk
                for chunk, _
                in block_chunks
            ]
        )

        self._ensure_index(
            len(vectors[0])
        )

        ids = []

        uid = metadata.get(
            "user_id",
            "default_user",
        )

        for (
            chunk,
            block_metadata,
        ), vector in zip(
            block_chunks,
            vectors,
        ):
            chunk_id = str(
                uuid.uuid4()
            )

            chunk_metadata = (
                metadata | block_metadata
            )

            payload = {
                "id": chunk_id,
                "text": chunk,
                "document_id": doc_id,
                "session_id": metadata.get(
                    "session_id",
                    "legacy",
                ),
                "user_id": uid,
                "source_type": metadata.get(
                    "source_type",
                    "text",
                ),
                "filename": metadata.get(
                    "filename",
                    "unknown",
                ),
                "page": chunk_metadata.get(
                    "page",
                    0,
                ),
                "section": chunk_metadata.get(
                    "section",
                    "",
                ),
                "timestamp_start": (
                    chunk_metadata.get(
                        "timestamp_start"
                    )
                    or ""
                ),
                "timestamp_end": (
                    chunk_metadata.get(
                        "timestamp_end"
                    )
                    or ""
                ),
                "line_start": (
                    chunk_metadata.get(
                        "line_start"
                    )
                    or ""
                ),
                "line_end": (
                    chunk_metadata.get(
                        "line_end"
                    )
                    or ""
                ),
                "metadata": json.dumps(
                    chunk_metadata
                ),
                "embedding": struct.pack(
                    f"{len(vector)}f",
                    *vector,
                ),
            }

            self.store.client.hset(
                f"{self.PREFIX}{chunk_id}",
                mapping=payload,
            )

            ids.append(chunk_id)

        logger.info(
            "Ingested %d chunks for "
            "document=%s session=%s user=%s",
            len(ids),
            doc_id,
            metadata.get(
                "session_id",
                "legacy",
            ),
            uid,
        )

        return ids

    @staticmethod
    def _cosine_similarity(
        a: list[float],
        b: list[float],
    ) -> float:
        """Cosine similarity between two equal-length vectors."""
        if (
            not a
            or not b
            or len(a) != len(b)
        ):
            return 0.0

        dot = sum(
            x * y
            for x, y in zip(a, b)
        )

        norm_a = sum(
            x * x
            for x in a
        ) ** 0.5

        norm_b = sum(
            y * y
            for y in b
        ) ** 0.5

        if (
            norm_a == 0.0
            or norm_b == 0.0
        ):
            return 0.0

        return dot / (
            norm_a * norm_b
        )

    def _rerank(
        self,
        candidates: list[dict],
        query_vector: list[float] | None,
        top_k: int,
        weight: float = 0.35,
        query_text: str = "",
    ) -> list[dict]:
        """Rerank RRF-fused candidates with strong lexical evidence.

        Ranking intentionally favors explicit lexical evidence for factual
        document questions. This prevents a generic semantically-similar
        chunk from displacing a chunk containing the actual requested terms.

        weight:
            1.0 -> purely RRF
            0.0 -> purely lexical
            0.35 -> RRF + strong lexical preference
        """
        if not candidates:
            return []

        # Inspect a reasonably large candidate pool before final selection.
        pool_size = min(
            len(candidates),
            max(top_k * 4, 20),
        )

        pool = candidates[:pool_size]

        # Use the original query for reranking.
        # Expanded variants are useful for retrieval, but they can introduce
        # unrelated terms that should NOT influence final evidence selection.
        terms = retrieval_terms(
            query_text
        )

        if not terms:
            terms = re.findall(
                r"[a-z0-9]+",
                query_text.lower(),
            )

        unique_terms = list(
            dict.fromkeys(
                t.lower()
                for t in terms
                if t
            )
        )

        query_term_set = set(
            unique_terms
        )

        max_rrf = max(
            item.get(
                "rrf_score",
                0.0,
            )
            for item in pool
        )

        if max_rrf <= 0.0:
            max_rrf = 1.0

        # Normalize each candidate.
        for item in pool:
            text = str(
                item.get(
                    "text",
                    "",
                )
            ).lower()

            text_terms = set(
                re.findall(
                    r"[a-z0-9]+",
                    text,
                )
            )

            if query_term_set:
                overlap = (
                    len(
                        query_term_set
                        & text_terms
                    )
                    / len(query_term_set)
                )
            else:
                overlap = 0.0

            normalized_rrf = (
                item.get(
                    "rrf_score",
                    0.0,
                )
                / max_rrf
            )

            # Count contiguous two-term matches.
            # This provides an additional signal for phrases such as
            # "tube light", "randomly selected", "string partition", etc.
            bigram_hits = 0
            if len(unique_terms) >= 2:
                for i in range(
                    len(unique_terms) - 1
                ):
                    first = unique_terms[i]
                    second = unique_terms[i + 1]

                    if (
                        re.search(
                            rf"\b{re.escape(first)}\s+"
                            rf"{re.escape(second)}\b",
                            text,
                        )
                        is not None
                    ):
                        bigram_hits += 1

            bigram_total = max(
                len(unique_terms) - 1,
                1,
            )

            phrase_score = min(
                bigram_hits
                / bigram_total,
                1.0,
            )

            # Lexical preference:
            # 50% term coverage + 15% phrase match
            lexical_score = (
                0.50 * overlap
                + 0.15 * phrase_score
            )

            # Final blend:
            # 35% RRF
            # 65% explicit lexical/phrase evidence
            rerank_score = (
                weight * normalized_rrf
                + (1.0 - weight)
                * lexical_score
            )

            item["rerank_score"] = round(
                rerank_score,
                6,
            )

            item["lexical_overlap"] = round(
                overlap,
                4,
            )

            item["phrase_score"] = round(
                phrase_score,
                4,
            )

        ranked = sorted(
            pool,
            key=lambda x: (
                x.get(
                    "rerank_score",
                    0.0,
                ),
                x.get(
                    "lexical_overlap",
                    0.0,
                ),
                x.get(
                    "rrf_score",
                    0.0,
                ),
                -len(
                    x.get(
                        "match_sources",
                        [],
                    )
                ),
            ),
            reverse=True,
        )

        final_results = ranked[:top_k]

        # Exact-evidence safeguard:
        # If any candidate contains >=75% of the query terms, make sure
        # at least the strongest such candidate survives the final cutoff.
        strong_lexical = [
            item
            for item in ranked
            if item.get(
                "lexical_overlap",
                0.0,
            )
            >= 0.75
        ]

        if strong_lexical:
            strongest = strong_lexical[0]

            strongest_id = self._chunk_key(
                strongest
            )

            selected_ids = {
                self._chunk_key(item)
                for item in final_results
            }

            if strongest_id not in selected_ids:
                final_results = [
                    strongest,
                    *[
                        item
                        for item in final_results
                        if self._chunk_key(item)
                        != strongest_id
                    ],
                ][:top_k]

        logger.debug(
            "RAG rerank query=%r candidates=%d "
            "selected=%d top_overlap=%.3f",
            query_text[:120],
            len(pool),
            len(final_results),
            (
                final_results[0].get(
                    "lexical_overlap",
                    0.0,
                )
                if final_results
                else 0.0
            ),
        )

        return final_results

    @staticmethod
    def _chunk_key(
        item: dict,
    ) -> str:
        """Stable identity for a chunk across search passes."""
        cid = item.get("id")

        if (
            cid
            and cid != item.get("document_id")
        ):
            return str(cid)

        text_hash = hashlib.md5(
            (
                item.get(
                    "text",
                    "",
                )[:200]
            ).encode(
                "utf-8",
                errors="replace",
            )
        ).hexdigest()[:12]

        return (
            f"{item.get('document_id', 'unknown')}:"
            f"{text_hash}"
        )

    def _search(
        self,
        query: str,
        top_k: int,
        document_ids: list[str] | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        query_vector: list[float] | None = None,
    ) -> tuple[
        list[dict],
        list[dict],
        dict[str, float],
    ]:
        timings: dict[str, float] = {}

        # ────────────────────────────────────────────────
        # 1. Lexical Search
        # ────────────────────────────────────────────────
        lex_start = time.perf_counter()

        lexical: list[dict] = []

        try:
            raw_terms = re.findall(
                r"[A-Za-z0-9_]+",
                query,
            )

            search_terms = (
                retrieval_terms(query)
                or raw_terms
            )

            tag_filters = []

            if user_id:
                tag_filters.append(
                    "@user_id:{"
                    f"{self._escape_tag(user_id)}"
                    "}"
                )

            if document_ids:
                doc_filter = " | ".join(
                    self._escape_tag(doc_id)
                    for doc_id in document_ids
                )

                tag_filters.append(
                    f"@document_id:{{{doc_filter}}}"
                )

            elif session_id:
                tag_filters.append(
                    "@session_id:{"
                    f"{self._escape_tag(session_id)}"
                    "}"
                )

            filter_str = " ".join(
                tag_filters
            )

            if search_terms:
                term_query = " | ".join(
                    search_terms
                )

                text_query = (
                    f"{filter_str} "
                    f"@text:({term_query})"
                    if filter_str
                    else f"@text:({term_query})"
                )

            else:
                text_query = (
                    filter_str
                    if filter_str
                    else "*"
                )

            logger.info(
                "Executing RediSearch Lexical Query: %s",
                text_query,
            )

            raw = self.store.client.execute_command(
                "FT.SEARCH",
                self.INDEX_NAME,
                text_query,
                "RETURN",
                "8",
                "id",
                "text",
                "document_id",
                "session_id",
                "source_type",
                "filename",
                "page",
                "section",
                "LIMIT",
                "0",
                str(
                    max(
                        top_k * 4,
                        50,
                    )
                ),
            )

            for item in self._parse_search_results(
                raw
            ):
                if (
                    document_ids
                    and item.get(
                        "document_id"
                    )
                    not in document_ids
                ):
                    continue

                lexical.append(item)

                # Keep more candidates for RRF/reranking.
                if len(lexical) >= max(
                    top_k * 4,
                    20,
                ):
                    break

        except Exception:
            logger.exception(
                "Redis lexical search failed"
            )

        timings["lexical_ms"] = round(
            (
                time.perf_counter()
                - lex_start
            )
            * 1000,
            2,
        )

        # ────────────────────────────────────────────────
        # 2. Embedding & Semantic Vector Search
        # ────────────────────────────────────────────────
        emb_start = time.perf_counter()

        semantic: list[dict] = []

        try:
            # Use pre-computed embedding when supplied.
            if query_vector is not None:
                vector = query_vector
                timings["embedding_ms"] = 0.0

            else:
                vector = self.embedder.embed(
                    [query]
                )[0]

                timings["embedding_ms"] = round(
                    (
                        time.perf_counter()
                        - emb_start
                    )
                    * 1000,
                    2,
                )

            vec_search_start = time.perf_counter()

            tag_filters = []

            if user_id:
                tag_filters.append(
                    "@user_id:{"
                    f"{self._escape_tag(user_id)}"
                    "}"
                )

            if document_ids:
                doc_filter = " | ".join(
                    self._escape_tag(doc_id)
                    for doc_id in document_ids
                )

                tag_filters.append(
                    f"@document_id:{{{doc_filter}}}"
                )

            elif session_id:
                tag_filters.append(
                    "@session_id:{"
                    f"{self._escape_tag(session_id)}"
                    "}"
                )

            filter_str = (
                " ".join(tag_filters)
                if tag_filters
                else "*"
            )

            vector_query = (
                f"({filter_str})=>"
                f"[KNN {top_k * 2} "
                f"@embedding $query AS score]"
            )

            logger.info(
                "Executing RediSearch Vector Query: %s",
                vector_query,
            )

            raw = self.store.client.execute_command(
                "FT.SEARCH",
                self.INDEX_NAME,
                vector_query,
                "PARAMS",
                "2",
                "query",
                struct.pack(
                    f"{len(vector)}f",
                    *vector,
                ),
                "SORTBY",
                "score",
                "ASC",
                "RETURN",
                "9",
                "id",
                "text",
                "document_id",
                "session_id",
                "source_type",
                "filename",
                "page",
                "section",
                "score",
                "DIALECT",
                "2",
            )

            for fields in self._parse_search_results(
                raw
            ):
                if (
                    document_ids
                    and fields.get(
                        "document_id"
                    )
                    not in document_ids
                ):
                    continue

                fields["score"] = float(
                    fields.get(
                        "score",
                        1.0,
                    )
                )

                semantic.append(fields)

            timings["vector_ms"] = round(
                (
                    time.perf_counter()
                    - vec_search_start
                )
                * 1000,
                2,
            )

        except Exception:
            timings.setdefault(
                "embedding_ms",
                round(
                    (
                        time.perf_counter()
                        - emb_start
                    )
                    * 1000,
                    2,
                ),
            )

            timings.setdefault(
                "vector_ms",
                0.0,
            )

            logger.exception(
                "Redis vector search failed"
            )

        return (
            lexical,
            semantic,
            timings,
        )

    def search_results(
        self,
        query: str,
        top_k: int = 8,
        document_ids: list[str] | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        """Hybrid retrieval with query understanding."""
        if user_id and document_ids:
            try:
                from services.document_service import DocumentService
                doc_svc = DocumentService()
                user_docs = doc_svc.list(user_id=user_id)
                allowed_ids = {str(d["id"]) for d in user_docs}
                document_ids = [did for did in document_ids if str(did) in allowed_ids]
                if not document_ids:
                    return []
            except Exception as e:
                logger.warning("Could not validate document ownership: %s", e)

        start_time = time.perf_counter()

        settings = get_settings()

        # ────────────────────────────────────────────────
        # 1. Generate query variants
        # ────────────────────────────────────────────────
        variants = generate_variants(
            query,
            settings.ollama_url,
            settings.ollama_llm_model,
        )

        if not variants:
            variants = [query]

        # ────────────────────────────────────────────────
        # 2. Batch-embed all variants
        # ────────────────────────────────────────────────
        emb_start = time.perf_counter()

        embeddings = self.embedder.embed(
            variants
        )

        timings: dict[str, float] = {
            "batch_embedding_ms": round(
                (
                    time.perf_counter()
                    - emb_start
                )
                * 1000,
                2,
            )
        }

        # Final result count remains compatible with callers.
        result_limit = min(
            max(top_k, 3),
            5,
        )

        # Retrieve a larger pool before reranking.
        search_k = max(
            10,
            result_limit * 4,
        )

        all_lexical: dict[
            str,
            tuple[int, dict],
        ] = {}

        all_semantic: dict[
            str,
            tuple[int, dict],
        ] = {}

        # ────────────────────────────────────────────────
        # 3. Search every query variant
        # ────────────────────────────────────────────────
        for variant, vec in zip(
            variants,
            embeddings,
        ):
            lexical, semantic, var_timings = (
                self._search(
                    variant,
                    search_k,
                    document_ids,
                    session_id,
                    user_id=user_id,
                    query_vector=vec,
                )
            )

            for key in (
                "lexical_ms",
                "embedding_ms",
                "vector_ms",
            ):
                timings[key] = var_timings.get(
                    key,
                    0,
                )

            for rank, item in enumerate(
                lexical,
                start=1,
            ):
                key = self._chunk_key(
                    item
                )

                if (
                    key not in all_lexical
                    or rank < all_lexical[key][0]
                ):
                    all_lexical[key] = (
                        rank,
                        item,
                    )

            for rank, item in enumerate(
                semantic,
                start=1,
            ):
                key = self._chunk_key(
                    item
                )

                if (
                    key not in all_semantic
                    or rank < all_semantic[key][0]
                ):
                    all_semantic[key] = (
                        rank,
                        item,
                    )

        # ────────────────────────────────────────────────
        # 4. RRF fusion
        # ────────────────────────────────────────────────
        rrf_start = time.perf_counter()

        ranked: dict[
            str,
            dict,
        ] = {}

        for key, (
            rank,
            item,
        ) in all_lexical.items():
            entry = ranked.setdefault(
                key,
                {
                    **item,
                    "rrf_score": 0.0,
                    "match_sources": [],
                },
            )

            entry["rrf_score"] += (
                1 / (60 + rank)
            )

            entry["match_sources"].append(
                f"lexical_rank_{rank}"
            )

        for key, (
            rank,
            item,
        ) in all_semantic.items():
            entry = ranked.setdefault(
                key,
                {
                    **item,
                    "rrf_score": 0.0,
                    "match_sources": [],
                },
            )

            entry["rrf_score"] += (
                1 / (60 + rank)
            )

            entry["match_sources"].append(
                f"semantic_rank_{rank}"
            )

        rrf_candidates = sorted(
            ranked.values(),
            key=lambda item: item.get(
                "rrf_score",
                0.0,
            ),
            reverse=True,
        )

        # IMPORTANT:
        # Use the ORIGINAL query for final reranking.
        # Query expansion helps retrieval, but should not contaminate the
        # evidence ranking with unrelated expansion terms.
        results = self._rerank(
            rrf_candidates,
            query_vector=None,
            top_k=result_limit,
            query_text=query,
        )

        timings["rrf_ms"] = round(
            (
                time.perf_counter()
                - rrf_start
            )
            * 1000,
            2,
        )

        # ────────────────────────────────────────────────
        # 5. Resilient document fallback
        # ────────────────────────────────────────────────
        if not results and document_ids:
            doc_filter = " | ".join(
                self._escape_tag(doc_id)
                for doc_id in document_ids
            )

            fallback_query = (
                f"@document_id:{{{doc_filter}}}"
            )

            if session_id:
                fallback_query += (
                    " @session_id:{"
                    f"{self._escape_tag(session_id)}"
                    "}"
                )

            try:
                raw_fb = (
                    self.store.client.execute_command(
                        "FT.SEARCH",
                        self.INDEX_NAME,
                        fallback_query,
                        "LIMIT",
                        "0",
                        str(result_limit),
                    )
                )

                for item in self._parse_search_results(
                    raw_fb
                ):
                    results.append(
                        {
                            **item,
                            "rrf_score": 0.01,
                            "match_sources": [
                                "document_chunk_fallback"
                            ],
                        }
                    )

            except Exception as fb_exc:
                logger.warning(
                    "RAG fallback query failed: %s",
                    fb_exc,
                )

        top_score = (
            results[0].get(
                "rrf_score",
                0.0,
            )
            if results
            else 0.0
        )

        duration_ms = round(
            (
                time.perf_counter()
                - start_time
            )
            * 1000,
            2,
        )

        logger.info(
            "RAG Search Complete: query='%s' "
            "variants=%d doc_ids=%s "
            "lexical=%d semantic=%d "
            "rrf=%d final=%d top=%.4f "
            "ms=%.2f "
            "(emb=%.1f lex_ms=%.1f "
            "vec_ms=%.1f rrf_ms=%.1f)",
            query[:60],
            len(variants),
            document_ids,
            len(all_lexical),
            len(all_semantic),
            len(ranked),
            len(results),
            top_score,
            duration_ms,
            timings.get(
                "batch_embedding_ms",
                0.0,
            ),
            timings.get(
                "lexical_ms",
                0.0,
            ),
            timings.get(
                "vector_ms",
                0.0,
            ),
            timings.get(
                "rrf_ms",
                0.0,
            ),
        )

        # Useful diagnostic information without dumping full documents.
        for idx, item in enumerate(
            results,
            start=1,
        ):
            logger.info(
                "RAG Selected #%d "
                "doc=%s "
                "rerank=%.4f "
                "lexical_overlap=%.4f "
                "phrase=%.4f "
                "rrf=%.4f "
                "text=%r",
                idx,
                item.get(
                    "document_id",
                    "unknown",
                ),
                item.get(
                    "rerank_score",
                    0.0,
                ),
                item.get(
                    "lexical_overlap",
                    0.0,
                ),
                item.get(
                    "phrase_score",
                    0.0,
                ),
                item.get(
                    "rrf_score",
                    0.0,
                ),
                str(
                    item.get(
                        "text",
                        "",
                    )
                )[:180],
            )

        return results

    def search(
        self,
        query: str,
        top_k: int = 3,
        document_ids: list[str] | None = None,
        session_id: str | None = None,
    ) -> str:
        return "\n\n".join(
            item.get(
                "text",
                "",
            )
            for item in self.search_results(
                query,
                top_k,
                document_ids,
                session_id,
            )
            if item.get("text")
        )