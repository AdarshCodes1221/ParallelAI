import logging
import os
import pdfplumber

from services.gemini_service import (
    GeminiService,
    GeminiServiceError,
)

logger = logging.getLogger(__name__)


class PDFParser:
    """
    Layer 1:
        pdfplumber (digital PDFs)

    Layer 2:
        Gemini OCR fallback (scanned PDFs)
    """

    @staticmethod
    def extract_text(
        file_path: str,
        api_key: str = None,
        model_name: str = "gemini-2.5-flash"
    ) -> str:

        # --------------------------------------------------
        # Debug Information
        # --------------------------------------------------
        try:
            exists = os.path.exists(file_path)
            size = os.path.getsize(file_path) if exists else 0

            logger.info(
                f"PDF path={file_path} "
                f"exists={exists} "
                f"size={size}"
            )

            logger.info(
                f"API key present={bool(api_key)} "
                f"model={model_name}"
            )

        except Exception as e:
            logger.exception(e)

        # --------------------------------------------------
        # Layer 1 : pdfplumber
        # --------------------------------------------------
        try:

            text_parts = []

            with pdfplumber.open(file_path) as pdf:

                logger.info(
                    f"PDF opened successfully. "
                    f"Pages={len(pdf.pages)}"
                )

                for page_num, page in enumerate(pdf.pages, start=1):

                    try:
                        text = page.extract_text()

                        if text:
                            text_parts.append(text)

                    except Exception as page_error:
                        logger.exception(
                            f"Page {page_num} failed: "
                            f"{page_error}"
                        )

            extracted = "\n\n".join(text_parts).strip()

            logger.info(
                f"pdfplumber extracted "
                f"{len(extracted)} chars"
            )

            if len(extracted) > 30:
                return extracted

            logger.warning(
                "Little/no text found. "
                "Switching to Gemini OCR."
            )

        except Exception as e:
            logger.exception(
                f"pdfplumber failed: {e}"
            )

        # --------------------------------------------------
        # Layer 2 : Gemini OCR
        # --------------------------------------------------
        if not api_key:

            return (
                "⚠️ Gemini OCR unavailable. "
                "API key missing."
            )

        try:

            prompt = """
Extract ALL text from this PDF.

Requirements:
- Preserve headings
- Preserve lists
- Preserve tables
- Preserve page order
- Return plain text only
"""

            with open(file_path, "rb") as f:
                pdf_bytes = f.read()

            logger.info(
                f"Sending PDF bytes to Gemini. "
                f"Size={len(pdf_bytes)}"
            )

            response = GeminiService.generate_content(
                [
                    {
                        "mime_type": "application/pdf",
                        "data": pdf_bytes,
                    },
                    prompt,
                ],
                api_key=api_key,
                model_name=model_name,
            )

            if getattr(response, "text", None):

                logger.info(
                    f"Gemini extracted "
                    f"{len(response.text)} chars"
                )

                return response.text.strip()

            return (
                "⚠️ Gemini OCR returned "
                "an empty response."
            )

        except GeminiServiceError as e:

            logger.exception(
                f"Gemini OCR failed: {e}"
            )

            return (
                f"⚠️ PDF extraction failed.\n"
                f"{str(e)}"
            )

        except Exception as e:

            logger.exception(
                f"Unexpected Gemini error: {e}"
            )

            return (
                f"⚠️ PDF extraction failed.\n"
                f"{str(e)}"
            )