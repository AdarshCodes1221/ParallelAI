from typing import Any

from services.providers.base import LLMProvider
from services.groq_service import GroqService


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: str):
        self.api_key = api_key
        if not api_key:
            raise ValueError("GROQ_API_KEY is not configured")

    def generate(self, prompt: Any, *, model: str, system_prompt: str | None = None, json_output: bool = False) -> str:
        selected_model = model if not model.removeprefix("models/").startswith("gemini-") else GroqService.DEFAULT_MODEL
        return GroqService.generate_text(prompt=str(prompt), api_key=self.api_key, model_name=selected_model, system_prompt=system_prompt)
