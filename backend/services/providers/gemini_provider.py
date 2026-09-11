import logging
from typing import Any, Sequence

from services.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    name = "gemini"
    DEFAULT_MODEL = "gemini-2.5-flash"

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured")
        from google import genai
        self.client = genai.Client(api_key=api_key)

    def generate(self, prompt: Any, *, model: str, system_prompt: str | None = None, json_output: bool = False) -> str:
        clean_model = model.removeprefix("models/") if model else self.DEFAULT_MODEL
        if not clean_model.startswith("gemini-"):
            logger.info("Gemini received non-Gemini model '%s'; normalizing to '%s'", model, self.DEFAULT_MODEL)
            clean_model = self.DEFAULT_MODEL
        contents = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        config = {"response_mime_type": "application/json"} if json_output else None
        response = self.client.models.generate_content(model=clean_model, contents=contents, config=config)
        return (getattr(response, "text", None) or "").strip()

    def embed(self, texts: Sequence[str], *, model: str) -> list[list[float]]:
        clean_model = model.removeprefix("models/") if model else "text-embedding-004"
        if not clean_model.startswith("text-embedding") and not clean_model.startswith("gemini"):
            clean_model = "text-embedding-004"
        response = self.client.models.embed_content(model=clean_model, contents=list(texts))
        return [list(getattr(item, "values", item)) for item in (getattr(response, "embeddings", None) or [])]
