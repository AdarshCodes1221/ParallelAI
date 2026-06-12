import logging
import google.generativeai as genai

logger = logging.getLogger(__name__)


class GeminiServiceError(Exception):
    def __init__(self, message: str, code: str = "unknown"):
        super().__init__(message)
        self.code = code


class GeminiService:
    """Central helper for Gemini API calls, retries, and friendly error mapping."""

    @staticmethod
    def configure(api_key: str):
        logger.info(
            "GeminiService.configure called: key_present=%s, key_prefix=%s",
            bool(api_key),
            (api_key[:10] + "...") if api_key else "N/A",
        )
        if not api_key:
            logger.error("GeminiService.configure: missing API key")
            raise GeminiServiceError(
                "Gemini API key is missing or not configured.",
                code="invalid_api_key"
            )
        genai.configure(api_key=api_key)

    @staticmethod
    def classify_error(exc: Exception) -> str:
        text = str(exc) or ""
        lower = text.lower()

        if "429" in text or "rate limit" in lower or "quota" in lower:
            return "rate_limit"
        if "invalid" in lower and "key" in lower:
            return "invalid_api_key"
        if "unauthorized" in lower or "401" in text or "403" in text:
            return "invalid_api_key"
        if "timeout" in lower or "timed out" in lower or "network" in lower or "connection" in lower:
            return "network_error"
        return "unknown_error"

    @staticmethod
    def friendly_error_message(exc: Exception) -> str:
        code = GeminiService.classify_error(exc)
        if code == "rate_limit":
            return (
                "Gemini rate limit or quota was exceeded. "
                "Please wait a moment and try again."
            )
        if code == "invalid_api_key":
            return (
                "Gemini API key is invalid or missing. "
                "Please verify your GEMINI_API_KEY configuration."
            )
        if code == "network_error":
            return (
                "A network or timeout error occurred while contacting Gemini. "
                "Please check your connection and retry."
            )
        return (
            "An unexpected error occurred while communicating with Gemini. "
            "Please try again later."
        )

    @staticmethod
    def should_fallback(exc: Exception) -> bool:
        return GeminiService.classify_error(exc) == "rate_limit"

    @staticmethod
    def generate_content(
        prompt,
        api_key: str,
        model_name: str = "gemini-2.5-flash",
        fallback_model_name: str = "gemini-2.5-flash-lite",
    ):
        GeminiService.configure(api_key)

        try:
            model = genai.GenerativeModel(model_name)
            return model.generate_content(prompt)
        except Exception as exc:
            logger.exception("Gemini generate_content failed for model=%s", model_name)
            if GeminiService.should_fallback(exc) and fallback_model_name:
                logger.warning(
                    "Gemini rate limit detected for %s, falling back to %s.",
                    model_name,
                    fallback_model_name,
                )
                try:
                    fallback = genai.GenerativeModel(fallback_model_name)
                    return fallback.generate_content(prompt)
                except Exception as fallback_exc:
                    logger.exception("Gemini fallback generate_content failed for model=%s", fallback_model_name)
                    raise GeminiServiceError(
                        GeminiService.friendly_error_message(fallback_exc),
                        code=GeminiService.classify_error(fallback_exc),
                    ) from fallback_exc
            raise GeminiServiceError(
                f"REAL GEMINI ERROR: {str(exc)}",
                code=GeminiService.classify_error(exc),
            ) from exc

    @staticmethod
    def embed_content(content, api_key: str, model_name: str = "models/text-embedding-004"):
        GeminiService.configure(api_key)
        try:
            return genai.embed_content(
                model=model_name,
                content=content,
                task_type="retrieval_document"
            )
        except Exception as exc:
            raise GeminiServiceError(
                GeminiService.friendly_error_message(exc),
                code=GeminiService.classify_error(exc),
            ) from exc

    @staticmethod
    def upload_file(file_path: str, mime_type: str | None = None):
        try:
            if mime_type:
                return genai.upload_file(path=file_path, mime_type=mime_type)
            return genai.upload_file(path=file_path)
        except Exception as exc:
            raise GeminiServiceError(
                GeminiService.friendly_error_message(exc),
                code=GeminiService.classify_error(exc),
            ) from exc

    @staticmethod
    def get_file(file_name: str):
        try:
            return genai.get_file(file_name)
        except Exception as exc:
            raise GeminiServiceError(
                GeminiService.friendly_error_message(exc),
                code=GeminiService.classify_error(exc),
            ) from exc
