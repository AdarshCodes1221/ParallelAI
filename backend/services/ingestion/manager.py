import os
from pathlib import Path

from schemas.evidence import EvidenceBlock, EvidenceDocument
from services.ingestion.pdf_ingestor import PDFIngestor
from services.ocr_service import OCRService
from services.audio_transcriber import AudioTranscriber

logger = __import__("logging").getLogger(__name__)


class IngestionManager:
    def __init__(self):
        self.pdf = PDFIngestor()

    def ingest(self, path: str, document_id: str, filename: str, mime_type: str) -> EvidenceDocument:
        if mime_type == "application/pdf" or Path(path).suffix.lower() == ".pdf":
            return self.pdf.ingest(path, document_id, filename, mime_type)
        if mime_type.startswith("image/"):
            return self._ingest_image(path, document_id, filename, mime_type)
        if mime_type.startswith("audio/") or mime_type.startswith("video/"):
            return self._ingest_audio(path, document_id, filename, mime_type)
        raise ValueError(f"No ingestor registered for {mime_type}")

    def _ingest_image(self, path: str, document_id: str, filename: str, mime_type: str) -> EvidenceDocument:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        text, confidence = OCRService.extract_text(
            path, mime_type,
            gemini_key=gemini_key if gemini_key else None,
        )
        visual = OCRService.analyze_visual(path, mime_type, gemini_key or None)
        block = EvidenceBlock(
            text=text or "",
            page=1,
            modality="image",
            metadata={"ocr_confidence": confidence, "visual": visual},
        )
        return EvidenceDocument(
            document_id=document_id,
            filename=Path(filename).name,
            mime_type=mime_type,
            source_type="image",
            text=text or "",
            blocks=[block],
            metadata={"page_count": 1, "ocr_confidence": confidence, "visual": visual},
        )

    def _ingest_audio(self, path: str, document_id: str, filename: str, mime_type: str) -> EvidenceDocument:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        transcript, meta = AudioTranscriber.transcribe(
            path, mime_type, gemini_key=gemini_key,
        )
        block = EvidenceBlock(
            text=transcript or "",
            page=1,
            modality="audio",
            timestamp_start=0,
            metadata=meta,
        )
        return EvidenceDocument(
            document_id=document_id,
            filename=Path(filename).name,
            mime_type=mime_type,
            source_type="audio",
            text=transcript or "",
            blocks=[block],
            metadata={"page_count": 1, "word_count": meta.get("word_count", 0)},
        )
