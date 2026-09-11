from pydantic import BaseModel


class Citation(BaseModel):
    citation_id: str
    document_id: str
    filename: str
    chunk_id: str
    page: int | None = None
    section: str | None = None
    timestamp_start: float | None = None
    timestamp_end: float | None = None
    line_start: int | None = None
    line_end: int | None = None
    score: float
    snippet: str


class AnswerResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    confidence: float = 0.0
    grounded: bool = False
    missing_information: list[str] = []
