from pydantic import BaseModel, Field
from services.groq_service import GroqService, GroqServiceError
from services.gemini_service import GeminiService, GeminiServiceError


class SummaryOutput(BaseModel):
    one_line_summary: str = Field(..., description="A concise one-line summary.")
    three_bullet_points: list[str] = Field(
        ...,
        description="Exactly three bullet points summarizing the key ideas.",
        min_length=3,
        max_length=3,
    )
    five_sentence_summary: str = Field(..., description="A detailed summary exactly five sentences long.")


class SummarizerService:
    """Service to generate structured summaries from text."""

    @staticmethod
    def get_system_prompt() -> str:
        # FIX TC1: prompt now explicitly requests Duration when audio metadata is present
        return (
            "You are an expert summarizer. You must format your response strictly as Markdown "
            "with the following sections:\n\n"
            "### 1-Line Summary\n"
            "[Write a concise one-line summary here]\n\n"
            "### Key Points\n"
            "- [Point 1]\n"
            "- [Point 2]\n"
            "- [Point 3]\n\n"
            "### Detailed Summary\n"
            "[Write exactly a 5-sentence summary here]\n\n"
            "### Duration\n"
            "[If AUDIO METADATA is present in the context, write the estimated duration here. "
            "Otherwise write 'N/A'.]"
        )

    @staticmethod
    def summarize(text: str, groq_api_key: str = None, gemini_api_key: str = None, model_name: str = None) -> str:
        prompt = f"{SummarizerService.get_system_prompt()}\n\nText to summarize:\n{text}"
        groq_key = groq_api_key or None
        gemini_key = gemini_api_key or None

        if groq_key:
            try:
                return GroqService.generate_text(
                    prompt,
                    api_key=groq_key,
                    model_name=model_name,
                    max_tokens=1024,
                )
            except GroqServiceError as e:
                logger = __import__("logging").getLogger(__name__)
                logger.warning("Groq summarization failed. Falling back to Gemini: %s", e)

        if gemini_key:
            try:
                result = GeminiService.generate_content(
                    prompt,
                    api_key=gemini_key,
                    model_name=model_name or "gemini-2.5-flash",
                )
                return result.text.strip()
            except GeminiServiceError as e:
                raise

        raise RuntimeError("No available summarization provider: GROQ_API_KEY or GEMINI_API_KEY is required.")