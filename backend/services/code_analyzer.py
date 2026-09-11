from pydantic import BaseModel, Field
from services.groq_service import GroqService, GroqServiceError
from services.gemini_service import GeminiService, GeminiServiceError
from services.providers.router import ProviderRouter


class CodeAnalysisOutput(BaseModel):
    language: str = Field(..., description="The programming language detected.")
    explanation: str = Field(..., description="A high-level explanation of what the code does.")
    bugs: list[str] = Field(..., description="A list of detected bugs or vulnerabilities. Empty list if none.")
    time_complexity: str = Field(..., description="The Big-O time complexity of the primary algorithm.")


class CodeAnalyzerService:
    """Service to analyze code snippets."""

    @staticmethod
    def get_system_prompt() -> str:
        # FIXED: was missing `return` and opening `(` — method returned None
        return (
            "You are an expert software engineer. Analyze the provided code snippet "
            "and format your response strictly as Markdown with these three sections:\n\n"
            "### Explanation\n"
            "[A clear, high-level explanation of what the code does]\n\n"
            "### Detected Bugs\n"
            "[List any bugs, vulnerabilities, or issues. If none, write 'None detected.']\n\n"
            "### Time Complexity\n"
            "[The Big-O time complexity of the primary algorithm with a brief justification]"
        )

    @staticmethod
    def analyze(code: str, groq_api_key: str = None, gemini_api_key: str = None, model_name: str = None) -> str:
        if not code or len(code.strip()) < 20:
            return "No valid code detected."

        prompt = f"{CodeAnalyzerService.get_system_prompt()}\n\nCode to analyze:\n```\n{code}\n```"
        return ProviderRouter().generate(
            prompt, model=model_name or "gemini-2.5-flash",
            system_prompt=CodeAnalyzerService.get_system_prompt(),
        )