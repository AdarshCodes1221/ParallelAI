class Planner:
    """Creates an execution plan from the required tools."""
    
    @staticmethod
    def create_plan(required_tools: list[str]) -> list[dict]:
        plan = []
        extraction_id = None
        for index, tool in enumerate(required_tools):
            node_id = f"task-{index + 1}"
            dependencies = []
            if tool in {"rag_search", "retrieve", "index_pdf", "summarizer", "sentiment", "code_analyzer"} and extraction_id:
                dependencies.append(extraction_id)
            plan.append({
                "id": node_id,
                "tool": tool,
                "status": "pending",
                "depends_on": dependencies,
                "can_run_parallel": tool not in {"rag_search", "retrieve", "synthesize"},
            })
            if tool in {"pdf_parser", "ocr", "audio_stt", "youtube_fetcher", "document_ingest", "index_pdf"}:
                extraction_id = node_id
        return plan
