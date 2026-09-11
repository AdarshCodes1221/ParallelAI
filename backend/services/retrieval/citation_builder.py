from schemas.citations import Citation


def build_citations(results: list[dict]) -> list[dict]:
    citations = []
    for index, result in enumerate(results, start=1):
        if not result.get("text") or not result.get("document_id"):
            continue
        citations.append(Citation(
            citation_id=f"S{index}",
            document_id=str(result["document_id"]),
            filename=str(result.get("filename", "unknown")),
            chunk_id=str(result.get("id", "")),
            page=int(result["page"]) if str(result.get("page", "")).isdigit() and int(result.get("page", 0)) > 0 else None,
            section=result.get("section") or None,
            timestamp_start=float(result["timestamp_start"]) if result.get("timestamp_start") not in (None, "") else None,
            timestamp_end=float(result["timestamp_end"]) if result.get("timestamp_end") not in (None, "") else None,
            line_start=int(result["line_start"]) if str(result.get("line_start", "")).isdigit() else None,
            line_end=int(result["line_end"]) if str(result.get("line_end", "")).isdigit() else None,
            score=float(result.get("rrf_score", result.get("score", 0.0))),
            snippet=str(result["text"])[:500],
        ).model_dump())
    return citations
