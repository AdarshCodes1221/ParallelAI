import os
import sys

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from services.rag_service import RAGService


class NoEmbeddingCalls:
    def embed(self, texts):
        raise AssertionError("reranker must not make candidate embedding calls")


def test_reranker_promotes_alias_match_without_ollama_embedding():
    service = RAGService.__new__(RAGService)
    service.embedder = NoEmbeddingCalls()
    candidates = [
        {"id": "weak", "text": "The preferred phone format is listed here.", "rrf_score": 0.02},
        {"id": "strong", "text": "Contact number: 555-0100", "rrf_score": 0.019},
    ]

    results = service._rerank(candidates, query_vector=None, top_k=2, query_text="mobile")

    assert results[0]["id"] == "strong"
    assert results[0]["lexical_overlap"] > results[1]["lexical_overlap"]


def test_search_results_returns_at_most_five_after_rrf(monkeypatch):
    service = RAGService.__new__(RAGService)
    service.embedder = type("Embedder", (), {"embed": lambda self, texts: [[1.0] for _ in texts]})()
    candidates = [
        ({"id": str(index), "text": f"project evidence {index}", "document_id": "doc", "rrf_score": 1 / (60 + index)},
         [])
        for index in range(8)
    ]

    monkeypatch.setattr("services.rag_service.generate_variants", lambda *args: ["projects"])
    monkeypatch.setattr(
        service,
        "_search",
        lambda *args, **kwargs: ([item for item, _ in candidates], [], {}),
    )

    results = service.search_results("projects", top_k=8, document_ids=["doc"], session_id="session")

    assert 3 <= len(results) <= 5
    assert all(item["document_id"] == "doc" for item in results)