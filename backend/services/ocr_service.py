import logging
from services.gemini_service import GeminiService, GeminiServiceError

logger = logging.getLogger(__name__)


class OCRService:
    """Extracts text from images. Uses Tesseract locally first, then Gemini Vision."""

    @staticmethod
    def extract_text(
        file_path: str,
        mime_type: str,
        gemini_key: str = None,
        model_name: str = "gemini-2.5-flash"
    ):
        logger.info(
            "OCRService.extract_text called: GEMINI_KEY_PRESENT=%s, KEY_PREFIX=%s, MODEL=%s, FILE=%s",
            bool(gemini_key),
            (gemini_key[:10] + "...") if gemini_key else "N/A",
            model_name,
            file_path,
        )
        # ── Layer 1: Tesseract (free, offline) ────────────────────────────
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(file_path)
            # get_data gives per-word confidence scores
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config="--psm 3")
            words = [w for w in data["text"] if w.strip()]
            confs = [c for c, w in zip(data["conf"], data["text"]) if w.strip() and c != -1]

            if words:
                text = " ".join(words)
                avg_conf = round(sum(confs) / len(confs) / 100, 2) if confs else 0.5
                logger.info(f"[OCR Layer 1] Tesseract extracted {len(words)} words, confidence={avg_conf}")
                logger.info("OCR ENGINE USED: TESSERACT")
                return text, avg_conf

        except Exception as e:
            logger.warning(f"[OCR Layer 1] Tesseract failed: {e}")

        # ── Layer 2: Gemini Vision fallback ───────────────────────────────
        if not gemini_key:
            logger.warning("OCRService: no gemini_key provided; returning early.")
            return "OCR Failed: No API key and Tesseract unavailable.", 0.0

        try:
            with open(file_path, "rb") as f:
                img_data = {"mime_type": mime_type, "data": f.read()}

            response = GeminiService.generate_content(
                [img_data, "Extract all text from this image accurately. Return only the extracted text."],
                api_key=gemini_key,
                model_name=model_name,
            )

            text = response.text.strip() if getattr(response, "text", None) else ""
            logger.info("OCR ENGINE USED: GEMINI; RESPONSE_LEN=%d", len(text))
            return text, 0.90

        except GeminiServiceError as e:
            logger.exception("[OCR Layer 2] Gemini Vision OCR Error: %s", e)
            return f"OCR Failed: {GeminiService.friendly_error_message(e)}", 0.0
        except Exception as e:
            logger.exception("[OCR Layer 2] Unexpected error: %s", e)
            return "OCR Failed: An unexpected error occurred.", 0.0