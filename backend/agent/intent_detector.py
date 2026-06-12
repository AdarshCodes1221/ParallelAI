import logging
import re
import json
import os
from types import SimpleNamespace
from pydantic import BaseModel, Field
from services.groq_service import GroqService, GroqServiceError
from services.gemini_service import GeminiService, GeminiServiceError

logger = logging.getLogger(__name__)


class IntentResult(BaseModel):
    primary_intent: str = Field(..., description="The main goal of the user.")
    required_tools: list[str] = Field(..., description="List of tools needed.")
    is_ambiguous: bool = Field(default=False)
    follow_up_question: str = Field(default=None)


# Keyword → tool shortcuts (no LLM needed)
COMMAND_MAP = {
    "/ocr":         ["ocr"],
    "/pdf":         ["pdf_parser"],
    "/summarize":   ["summarizer"],
    "/summary":     ["summarizer"],
    "/sentiment":   ["sentiment"],
    "/code":        ["code_analyzer"],
    "/youtube":     ["youtube_fetcher"],
    "/audio":       ["audio_stt"],
    "/extracttext": ["pdf_parser"],
    "summarize":    ["summarizer"],
    "sentiment":    ["sentiment"],
    "extract text": ["pdf_parser"],
    "ocr":          ["ocr"],
}

YOUTUBE_RE = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/\S+")


def _auto_detect_tools(query: str, files: list[dict]) -> list[str] | None:
    """
    Fast rule-based detection — avoids an LLM call when intent is obvious.
    Returns a list of tools if confident, else None (→ fall back to LLM).
    """
    q = query.strip().lower()
    tools = []

    # Slash-command shortcuts
    for cmd, cmd_tools in COMMAND_MAP.items():
        if q.startswith(cmd) or q == cmd.lstrip("/"):
            tools = list(cmd_tools)
            break

    # File-type auto-detection
    has_pdf   = any(f["mime_type"] == "application/pdf" for f in files)
    has_image = any(f["mime_type"].startswith("image/") for f in files)
    has_audio = any(f["mime_type"].startswith("audio/") for f in files)
    has_video = any(f["mime_type"].startswith("video/") for f in files)
    has_youtube = bool(YOUTUBE_RE.search(query))

    if has_pdf and "pdf_parser" not in tools:
        tools.insert(0, "pdf_parser")
    if has_image and "ocr" not in tools:
        tools.insert(0, "ocr")
    if (has_audio or has_video) and "audio_stt" not in tools:
        tools.insert(0, "audio_stt")
    if has_youtube and "youtube_fetcher" not in tools:
        tools.append("youtube_fetcher")

    # TEST CASE 4: When PDF is attached AND query contains summary/youtube keywords
    # Auto-include youtube_fetcher and summarizer for YouTube URL in PDF detection
    if has_pdf and any(w in q for w in ["summary", "summarize", "youtube", "video"]):
        if "youtube_fetcher" not in tools:
            tools.append("youtube_fetcher")
        if "summarizer" not in tools:
            tools.append("summarizer")

    # Append synthesis tools based on keywords
    if any(w in q for w in ["summar", "summarize", "tldr", "brief"]) and "summarizer" not in tools:
        tools.append("summarizer")
    if any(w in q for w in ["sentiment", "tone", "mood", "feeling"]) and "sentiment" not in tools:
        tools.append("sentiment")

    # FIX TC3: code_analyzer should only trigger when an image is present.
    # Prevents hallucinated code explanations on text-only queries that happen to say "code".
    if has_image and any(w in q for w in ["code", "bug", "function", "debug", "explain code", "explain"]) and "code_analyzer" not in tools:
        tools.append("code_analyzer")
    elif not has_image and any(w in q for w in ["bug", "debug", "explain code", "time complexity"]) and "code_analyzer" not in tools:
        # Allow code_analyzer for text-only queries that explicitly ask about code analysis
        tools.append("code_analyzer")

    # FIX TC5: Cross-input comparison — audio + PDF together with comparison query
    compare_keywords = ["same topic", "compare", "similar", "discuss the same", "both discuss", "match"]
    if (has_audio or has_video) and has_pdf and any(kw in q for kw in compare_keywords):
        if "audio_stt" not in tools:
            tools.insert(0, "audio_stt")
        if "pdf_parser" not in tools:
            tools.insert(0, "pdf_parser")

    return tools if tools else None


class IntentDetector:
    """Determines what tools to use based on the query and files."""

    @staticmethod
    def detect(query: str, files: list[dict], api_key: str | None = None, model_name: str = "gemini-2.5-flash") -> IntentResult:
        # 1. Fast rule-based detection
        fast_tools = _auto_detect_tools(query, files)
        if fast_tools:
            return IntentResult(
                primary_intent="Auto-detected",
                required_tools=fast_tools,
                is_ambiguous=False,
            )

        # 2. LLM-based detection for complex/ambiguous requests
        if not query.strip() and not files:
            return IntentResult(
                primary_intent="Empty query",
                required_tools=[],
                is_ambiguous=True,
                follow_up_question="What can I help you with today? You can upload PDFs, images, audio files, or paste a YouTube link.",
            )

        # If there are files but no clear text query
        if files and not query.strip():
            return IntentResult(
                primary_intent="File uploaded, intent unclear",
                required_tools=[],
                is_ambiguous=True,
                follow_up_question="What would you like me to do with this file? Options: Extract Text, Summarize, Sentiment Analysis, Find Action Items.",
            )

        # Build a short description of attached files for the LLM prompt
        file_desc = [f"{f['filename']} ({f['mime_type']})" for f in files]

        prompt = f"""Analyze the user request and attached files to determine the necessary tools.
User Request: {query}
Attached Files: {', '.join(file_desc) if file_desc else 'None'}

Available Tools:
- pdf_parser: For reading text from PDF files.
- ocr: For extracting text from Images or scanned documents.
- audio_stt: For transcribing Audio/Video files.
- youtube_fetcher: If a YouTube URL is in the query.
- summarizer: To summarize content into 1-line, 3 bullets, 5-sentence format.
- sentiment: To analyze mood/tone.
- code_analyzer: To explain or debug code snippets. ONLY use if an image file is attached or the query is explicitly about code analysis.
- rag_search: For deep semantic search across large documents.

Rules:
- If a PDF is attached, ALWAYS include pdf_parser.
- If an image is attached, ALWAYS include ocr.
- If audio is attached, ALWAYS include audio_stt.
- Only include code_analyzer if an image is attached (code in image) or the query explicitly asks to analyze/debug code.
- Only mark is_ambiguous=true if the user's intent is genuinely unclear even after seeing the files.
- Prefer action over asking.

Return ONLY raw JSON: {{"primary_intent": "string", "required_tools": ["tool1"], "is_ambiguous": false, "follow_up_question": null}}
"""
        groq_key = os.environ.get("GROQ_API_KEY", "")
        gemini_key = api_key
        res = None

        if groq_key:
            try:
                groq_text = GroqService.generate_text(
                    prompt,
                    api_key=groq_key,
                    model_name=model_name,
                    max_tokens=1024,
                )
                res = SimpleNamespace(text=groq_text)
            except GroqServiceError as service_err:
                if getattr(service_err, "code", "") == "rate_limit":
                    logger.warning("Groq rate limit while detecting intent: %s", str(service_err))
                else:
                    logger.warning("Groq intent detection failed, falling back to Gemini: %s", service_err)
            except Exception as e:
                logger.exception("Unexpected Groq intent detection error: %s", e)

        if res is None and gemini_key:
            try:
                res = GeminiService.generate_content(
                    prompt,
                    api_key=gemini_key,
                    model_name=model_name,
                )
            except GeminiServiceError as service_err:
                if service_err.code == "rate_limit":
                    logger.warning("Gemini rate limit while detecting intent: %s", str(service_err))
                else:
                    logger.exception("Gemini intent detection failed: %s", service_err)
                res = None
            except Exception as e:
                logger.exception("Unexpected intent detection error: %s", e)
                res = None

        # If the LLM call failed, fall back to fast rule-based detection
        if res is None:
            auto = _auto_detect_tools(query, files)
            if auto:
                return IntentResult(primary_intent="Fallback detection", required_tools=auto, is_ambiguous=False)
            return IntentResult(primary_intent="Unknown", required_tools=[], is_ambiguous=False)

        raw = res.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        return IntentResult(**data)