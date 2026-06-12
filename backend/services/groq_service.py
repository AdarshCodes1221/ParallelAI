import logging
import os
import time

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Groq error class — mirrors the shape of GeminiServiceError
# so callers can handle both with the same pattern.
# ─────────────────────────────────────────────────────────────
class GroqServiceError(Exception):
    def __init__(self, message: str, code: str = "unknown"):
        super().__init__(message)
        self.code = code


class GroqService:
    """
    Central helper for Groq API text-generation calls.

    Used ONLY for text-in / text-out tasks:
        - Summarization
        - Sentiment analysis
        - Code analysis
        - Final agent response generation

    NOT used for:
        - PDF parsing       → GeminiService
        - OCR               → GeminiService
        - Audio STT         → GeminiService
        - File uploads      → GeminiService
    """

    # Default model — fast, large context, free tier friendly
    DEFAULT_MODEL = "llama-3.3-70b-versatile"

    # Retry configuration
    MAX_RETRIES = 2
    RETRY_DELAY_SEC = 3
    REQUEST_TIMEOUT_SEC = 30

    # ── Error helpers ─────────────────────────────────────────

    @staticmethod
    def classify_error(exc: Exception) -> str:
        text = str(exc) or ""
        lower = text.lower()
        if "429" in text or "rate limit" in lower or "quota" in lower or "too many" in lower:
            return "rate_limit"
        if "401" in text or "403" in text or "invalid" in lower and "key" in lower:
            return "invalid_api_key"
        if "timeout" in lower or "timed out" in lower or "connection" in lower or "network" in lower:
            return "network_error"
        return "unknown_error"

    @staticmethod
    def friendly_error_message(exc: Exception) -> str:
        code = GroqService.classify_error(exc)
        if code == "rate_limit":
            return (
                "Groq rate limit reached. "
                "Falling back to Gemini or waiting a moment before retrying."
            )
        if code == "invalid_api_key":
            return (
                "Groq API key is invalid or missing. "
                "Please verify your GROQ_API_KEY environment variable."
            )
        if code == "network_error":
            return (
                "A network or timeout error occurred while contacting Groq. "
                "Please check your connection and retry."
            )
        return "An unexpected error occurred while communicating with Groq."

    @staticmethod
    def is_rate_limit(exc: Exception) -> bool:
        return GroqService.classify_error(exc) == "rate_limit"

    # ── Core generation ───────────────────────────────────────

    @staticmethod
    def generate_text(
        prompt: str,
        api_key: str = None,
        model_name: str = None,
        system_prompt: str = None,
        max_tokens: int = 2048,
    ) -> str:
        """
        Send a text prompt to Groq and return the response string.

        Parameters
        ----------
        prompt        : The user message / full prompt string.
        api_key       : GROQ_API_KEY. Falls back to os.environ if not passed.
        model_name    : Groq model to use. Defaults to llama-3.3-70b-versatile.
        system_prompt : Optional system instruction prepended to the conversation.
        max_tokens    : Max tokens to generate.

        Returns
        -------
        str — the model's text response.

        Raises
        ------
        GroqServiceError on all failures after retries.
        """
        resolved_key = api_key or os.environ.get("GROQ_API_KEY", "")
        if not resolved_key:
            raise GroqServiceError(
                "GROQ_API_KEY is missing or not configured.",
                code="invalid_api_key",
            )

        resolved_model = model_name or GroqService.DEFAULT_MODEL

        # Build message list
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        last_exc = None
        for attempt in range(1, GroqService.MAX_RETRIES + 2):  # +2 → attempts 1,2,3
            try:
                # Import here so the package is optional until Groq is actually used
                from groq import Groq  # pip install groq

                client = Groq(api_key=resolved_key, timeout=GroqService.REQUEST_TIMEOUT_SEC)

                logger.info(
                    "[Groq] Attempt %d/%d — model=%s",
                    attempt,
                    GroqService.MAX_RETRIES + 1,
                    resolved_model,
                )

                completion = client.chat.completions.create(
                    model=resolved_model,
                    messages=messages,
                    max_tokens=max_tokens,
                )

                text = completion.choices[0].message.content or ""
                logger.info("[Groq] ✅ Response received (%d chars)", len(text))
                return text.strip()

            except Exception as exc:
                last_exc = exc
                code = GroqService.classify_error(exc)
                logger.warning("[Groq] Attempt %d failed (%s): %s", attempt, code, exc)

                # Don't retry on auth errors — they won't recover
                if code == "invalid_api_key":
                    break

                if attempt <= GroqService.MAX_RETRIES:
                    wait = GroqService.RETRY_DELAY_SEC * attempt
                    logger.info("[Groq] Retrying in %ds…", wait)
                    time.sleep(wait)

        raise GroqServiceError(
            GroqService.friendly_error_message(last_exc),
            code=GroqService.classify_error(last_exc),
        ) from last_exc