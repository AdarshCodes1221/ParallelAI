from abc import ABC, abstractmethod
from typing import Any, Sequence


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, prompt: Any, *, model: str, system_prompt: str | None = None, json_output: bool = False) -> str:
        raise NotImplementedError

    def embed(self, texts: Sequence[str], *, model: str) -> list[list[float]]:
        raise NotImplementedError(f"{self.name} does not support embeddings")
