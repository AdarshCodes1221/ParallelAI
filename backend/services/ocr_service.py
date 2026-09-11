import logging
import re
import json
from core.config import get_settings
from services.gemini_service import GeminiService, GeminiServiceError

logger = logging.getLogger(__name__)

_URL_CANDIDATE_RE = re.compile(
    r"https?\s*:?\s*/{0,2}\s*[a-z0-9.-]+(?:\s*\.\s*[a-z]{2,})"
    r"(?:\s*/\s*[a-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+)*",
    re.IGNORECASE,
)


def _normalize_ocr_urls(text: str) -> str:
    """Join spacing inside URL-shaped OCR spans without inventing links."""
    def normalize(match: re.Match[str]) -> str:
        candidate = re.sub(r"\s+", "", match.group(0))
        candidate = re.sub(r"^(https?):/{0,2}", r"\1://", candidate, flags=re.IGNORECASE)
        return candidate

    return _URL_CANDIDATE_RE.sub(normalize, text)


def _ocr_image_pass(image, config: str):
    import pytesseract

    data = pytesseract.image_to_data(
        image,
        output_type=pytesseract.Output.DICT,
        config=config,
    )
    words = []
    confidences = []
    for word, confidence in zip(data["text"], data["conf"]):
        if not word.strip():
            continue
        words.append(word.strip())
        try:
            numeric_confidence = float(confidence)
        except (TypeError, ValueError):
            numeric_confidence = -1
        if numeric_confidence >= 0:
            confidences.append(numeric_confidence)
    text = _normalize_ocr_urls(" ".join(words))
    average_confidence = sum(confidences) / len(confidences) / 100 if confidences else 0.0
    return text, round(average_confidence, 2)


def _preprocessed_images(image):
    from PIL import Image as PILImage, ImageOps, ImageFilter

    scale = 2 if max(image.size) < 2200 else 1
    if scale > 1:
        image = image.resize((image.width * scale, image.height * scale), PILImage.Resampling.LANCZOS)
    grayscale = ImageOps.grayscale(image)
    contrast = ImageOps.autocontrast(grayscale)
    denoised = contrast.filter(ImageFilter.MedianFilter(size=3))
    thresholded = denoised.point(lambda value: 255 if value > 180 else 0)
    return (image, grayscale, denoised, thresholded)


class OCRService:
    """Extracts text from images. Uses Tesseract locally first, then Gemini Vision."""

    @staticmethod
    def extract_text(
        file_path: str,
        mime_type: str,
        gemini_key: str = None,
        model_name: str = "gemini-2.5-flash"
    ):
        logger.info("OCRService.extract_text called: GEMINI_KEY_PRESENT=%s, MODEL=%s, FILE=%s", bool(gemini_key), model_name, file_path)
        # ── Layer 1: Tesseract (free, offline) ────────────────────────────
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(file_path).convert("RGB")
            candidates = []
            for processed in _preprocessed_images(img):
                for psm in (6, 11):
                    text, avg_conf = _ocr_image_pass(processed, f"--oem 3 --psm {psm}")
                    if text:
                        candidates.append((avg_conf, text))

            if candidates:
                avg_conf, text = max(candidates, key=lambda candidate: (candidate[0], len(candidate[1])))
                logger.info(f"[OCR Layer 1] Tesseract extracted {len(text.split())} words, confidence={avg_conf}")
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

    @staticmethod
    def analyze_visual(file_path: str, mime_type: str, gemini_key: str | None = None) -> dict:
        """Return only OCR-verifiable links and recognized icon labels."""
        result = {"icons": [], "links": []}
        try:
            import pytesseract
            from PIL import Image

            image = Image.open(file_path)
            image = image.convert("RGB")
            candidates = []
            for processed in _preprocessed_images(image):
                text, confidence = _ocr_image_pass(processed, "--oem 3 --psm 11")
                if text:
                    candidates.append((confidence, text))
            text = max(candidates, key=lambda candidate: (candidate[0], len(candidate[1])))[1] if candidates else ""
            data = pytesseract.image_to_data(
                _preprocessed_images(image)[0],
                output_type=pytesseract.Output.DICT,
                config="--oem 3 --psm 11",
            )
            words = []
            for index, value in enumerate(data["text"]):
                value = value.strip()
                if not value:
                    continue
                words.append(value)
                label = value.lower().rstrip(":")
                known = {"github": "GitHub", "linkedin": "LinkedIn", "email": "email", "portfolio": "portfolio", "website": "website"}
                if label in known:
                    result["icons"].append({
                        "icon": known[label],
                        "bbox": {
                            "left": data["left"][index], "top": data["top"][index],
                            "width": data["width"][index], "height": data["height"][index],
                        },
                        "url": None,
                    })
            visible_text = _normalize_ocr_urls(text or " ".join(words))
            result["links"] = re.findall(r"https?://[^\s<>()]+", visible_text)
            for icon in result["icons"]:
                nearby = next((link for link in result["links"] if icon["icon"].lower() in link.lower()), None)
                icon["url"] = nearby
            if result["icons"] or result["links"]:
                return result
        except Exception as exc:
            logger.warning("Visual evidence extraction failed: %s", type(exc).__name__)

        if gemini_key and get_settings().llm_mode not in {"local", "offline"}:
            try:
                response = GeminiService.generate_content(
                    [{"mime_type": mime_type, "data": open(file_path, "rb").read()},
                     "Identify only visible social/contact icons and exact visible URLs. Return JSON with icons and links. Never infer or invent URLs."],
                    api_key=gemini_key,
                    model_name="gemini-2.5-flash",
                )
                parsed = json.loads((response.text or "{}").replace("```json", "").replace("```", "").strip())
                return parsed if isinstance(parsed, dict) else result
            except Exception:
                pass
        return result