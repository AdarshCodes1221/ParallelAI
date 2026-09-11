import logging
from pathlib import Path

import pdfplumber

from schemas.evidence import EvidenceBlock, EvidenceDocument

logger = logging.getLogger(__name__)


class PDFIngestor:
    def ingest(self, path: str, document_id: str, filename: str, mime_type: str = "application/pdf") -> EvidenceDocument:
        blocks: list[EvidenceBlock] = []
        links: list[dict] = []
        try:
            import fitz
            with fitz.open(path) as source_pdf:
                for page_number, page in enumerate(source_pdf, start=1):
                    for link in page.get_links():
                        if link.get("uri"):
                            links.append({"uri": link["uri"], "page": page_number, "bbox": link.get("from")})
        except Exception as exc:
            logger.warning("PDF URI metadata extraction failed: %s", type(exc).__name__)
        with pdfplumber.open(path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                text = (page.extract_text() or "").strip()
                tables = page.extract_tables() or []
                if text:
                    blocks.append(EvidenceBlock(text=text, page=page_number, modality="pdf"))
                for table_index, table in enumerate(tables, start=1):
                    rows = [" | ".join(str(cell or "") for cell in row) for row in table]
                    table_text = "\n".join(row for row in rows if row.strip())
                    if table_text:
                        blocks.append(EvidenceBlock(text=table_text, page=page_number, section=f"Table {table_index}", modality="table"))
        for block in blocks:
            block.metadata["verified_links"] = [link for link in links if link["page"] == block.page]
        return EvidenceDocument(
            document_id=document_id,
            filename=Path(filename).name,
            mime_type=mime_type,
            source_type="pdf",
            text="\n\n".join(block.text for block in blocks),
            blocks=blocks,
            metadata={"page_count": len({block.page for block in blocks if block.page is not None}), "links": links},
        )
