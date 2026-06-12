from pydantic import BaseModel, Field
from services.groq_service import GroqService, GroqServiceError
from services.gemini_service import GeminiService, GeminiServiceError

class SentimentOutput(BaseModel):
    label: str = Field(..., description="The sentiment label: POSITIVE, NEGATIVE, or NEUTRAL.")
    confidence: float = Field(..., description="A confidence score between 0.0 and 1.0.")
    justification: str = Field(..., description="A brief justification for why this sentiment was chosen.")

class SentimentService:
    """Service to analyze sentiment of extracted text."""
    
    @staticmethod
    def get_system_prompt() -> str:
        return (
            "You are a sentiment analysis expert. Analyze the text and format your response strictly as Markdown with the following sections:\n"
            "### Sentiment Label\n[POSITIVE, NEGATIVE, or NEUTRAL]\n\n"
            "### Confidence Score\n[e.g., 0.95]\n\n"
            "### Justification\n[One-line explanation of the reasoning]"
        )

    @staticmethod
    def analyze(text: str, groq_api_key: str = None, gemini_api_key: str = None, model_name: str = None) -> str:
        prompt = f"{SentimentService.get_system_prompt()}\n\nText to analyze:\n{text}"
        groq_key = groq_api_key or None
        gemini_key = gemini_api_key or None

        if groq_key:
            try:
                return GroqService.generate_text(
                    prompt,
                    api_key=groq_key,
                    model_name=model_name,
                    max_tokens=512,
                )
            except GroqServiceError as e:
                logger = __import__("logging").getLogger(__name__)
                logger.warning("Groq sentiment analysis failed. Falling back to Gemini: %s", e)

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

        raise RuntimeError("No available sentiment provider: GROQ_API_KEY or GEMINI_API_KEY is required.")
