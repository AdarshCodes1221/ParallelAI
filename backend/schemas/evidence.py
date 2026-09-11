from typing import Any

from pydantic import BaseModel, Field


class EvidenceBlock(BaseModel):
    text: str
    page: int | None = None
    section: str | None = None
    timestamp_start: float | None = None
    timestamp_end: float | None = None
    line_start: int | None = None
    line_end: int | None = None
    modality: str = "text"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceDocument(BaseModel):
    document_id: str
    filename: str
    mime_type: str
    source_type: str
    text: str = ""
    blocks: list[EvidenceBlock] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
