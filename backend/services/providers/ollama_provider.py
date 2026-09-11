import json
import urllib.error
import urllib.request
from typing import Any

from core.config import get_settings
from services.providers.base import LLMProvider


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, url: str | None = None):
        settings = get_settings()
        self.url = (url or settings.ollama_url).rstrip("/")
        self.default_model = settings.ollama_llm_model

    def generate(
        self,
        prompt: Any,
        *,
        model: str,
        system_prompt: str | None = None,
        json_output: bool = False,
    ) -> str:
        payload = {
            "model": self.default_model or "llama3.2:3b",
            "prompt": str(prompt),
            "stream": False,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if json_output:
            payload["format"] = "json"
        request = urllib.request.Request(
            f"{self.url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama request failed: {type(exc).__name__}") from exc
        text = result.get("response", "")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("Ollama returned an empty response")
        return text.strip()
