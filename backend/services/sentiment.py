from pydantic import BaseModel, Field
from services.providers.router import ProviderRouter


class SentimentOutput(BaseModel):
    label: str = Field(..., description="The sentiment label: Positive, Negative, Neutral, or Mixed.")
    confidence: float = Field(..., description="A confidence score between 0.0 and 1.0.")
    reason: str = Field(..., description="A brief evidence-based justification.")
    evidence: str = Field(..., description="A short relevant excerpt from the text.")


class SentimentService:
    """Service to analyze sentiment of extracted or conversational text."""

    @staticmethod
    def get_system_prompt() -> str:
        return (
            "You are a specialized multimodal sentiment analysis expert. Analyze the provided text and output strictly in the following structured Markdown format:\n\n"
            "### Sentiment Analysis\n\n"
            "- **Label:** [Positive / Negative / Neutral / Mixed]\n"
            "- **Confidence:** [Number between 0.00 and 1.00]\n"
            "- **Reason:** [Brief, evidence-based explanation of why this sentiment applies]\n"
            "- **Evidence:** \"[Short, exact excerpt or citation from the text demonstrating the tone]\"\n\n"
            "Rules:\n"
            "1. Base your analysis STRICTLY on the provided text. Do NOT hallucinate evidence.\n"
            "2. If the text expresses mixed emotions, use 'Mixed'.\n"
            "3. If the text is purely factual, technical, or informational without emotional bias, use 'Neutral'."
        )

    @staticmethod
    def analyze(text: str, groq_api_key: str | None = None, gemini_api_key: str | None = None, model_name: str | None = None) -> str:
        clean_text = (text or "").strip()
        if not clean_text:
            return "Please provide or attach the text, document, audio, or video you would like me to analyze for sentiment."
        prompt = f"{SentimentService.get_system_prompt()}\n\nText to analyze:\n{clean_text}"
        return ProviderRouter().generate(
            prompt, model=model_name or "llama3.2:3b",
            system_prompt=SentimentService.get_system_prompt(),
        )

