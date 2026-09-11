from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelDefinition:
    id: str
    label: str
    provider: str
    capabilities: tuple[str, ...]


MODELS = (
    ModelDefinition("gemini-2.5-flash", "Gemini 2.5 Flash", "gemini", ("text", "image", "audio", "video", "pdf", "structured_output", "function_calling")),
    ModelDefinition("gemini-2.5-pro", "Gemini 2.5 Pro", "gemini", ("text", "image", "audio", "video", "pdf", "structured_output", "function_calling")),
    ModelDefinition("gemini-3.5-flash", "Gemini 3.5 Flash", "gemini", ("text", "image", "audio", "video", "pdf", "structured_output", "function_calling")),
    ModelDefinition("llama-3.3-70b-versatile", "Llama 3.3 70B", "groq", ("text", "structured_output", "function_calling")),
)


def list_models() -> list[dict]:
    return [asdict(model) for model in MODELS]
