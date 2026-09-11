import logging
import os
from typing import Any

from core.config import get_settings
from services.providers.base import LLMProvider
from services.providers.gemini_provider import GeminiProvider
from services.providers.groq_provider import GroqProvider
from services.providers.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)


class ProviderRouter:
    def __init__(self, providers: dict[str, LLMProvider] | None = None):
        self.providers = providers or self._configured_providers()
        settings = get_settings()
        self.primary = settings.primary_llm_provider
        self.fallback = settings.fallback_llm_provider
        self.last_provider: str | None = None

    @staticmethod
    def _configured_providers() -> dict[str, LLMProvider]:
        providers: dict[str, LLMProvider] = {}
        providers["ollama"] = OllamaProvider()
        if os.getenv("GEMINI_API_KEY"):
            providers["gemini"] = GeminiProvider(os.environ["GEMINI_API_KEY"])
        if os.getenv("GROQ_API_KEY"):
            providers["groq"] = GroqProvider(os.environ["GROQ_API_KEY"])
        return providers

    def generate(self, prompt: Any, *, model: str, system_prompt: str | None = None, json_output: bool = False) -> str:
        text, _ = self.generate_with_metadata(
            prompt,
            model=model,
            system_prompt=system_prompt,
            json_output=json_output,
        )
        return text

    def generate_with_metadata(
        self,
        prompt: Any,
        *,
        model: str,
        system_prompt: str | None = None,
        json_output: bool = False,
        providers: tuple[str, ...] | None = None,
    ) -> tuple[str, str]:
        errors = []
        # Local generation is authoritative. Cloud providers are only fallback
        # capabilities after Ollama genuinely fails.
        provider_names = providers or ("ollama", self.fallback, "groq", "gemini")
        for provider_name in dict.fromkeys(provider_names):
            provider = self.providers.get(provider_name)
            if not provider:
                continue
            try:
                # Ensure model matches provider's expected namespace
                provider_model = model
                if provider_name == "ollama":
                    provider_model = getattr(provider, "default_model", "llama3.2:3b")
                elif provider_name == "gemini":
                    clean = model.removeprefix("models/") if model else ""
                    provider_model = clean if clean.startswith("gemini-") else "gemini-2.5-flash"
                elif provider_name == "groq":
                    clean = model.removeprefix("models/") if model else ""
                    provider_model = "llama-3.3-70b-versatile" if (clean.startswith("gemini-") or "llama3.2:3b" in clean) else clean

                text = provider.generate(prompt, model=provider_model, system_prompt=system_prompt, json_output=json_output)
                self.last_provider = provider_name
                logger.info("llm_response provider=%s model=%s", provider_name, provider_model)
                return text, provider_name
            except Exception as exc:
                errors.append(f"{provider_name}: {exc}")
                logger.warning("Provider %s failed: %s", provider_name, exc)
        raise RuntimeError("All configured LLM providers failed: " + "; ".join(errors))
