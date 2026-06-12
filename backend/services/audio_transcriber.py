"""
Audio Speech-to-Text transcriber with a three-tier provider strategy:

  Tier 1 — Groq Whisper   (fast, free tier, up to 25 MB per file)
  Tier 2 — Gemini          (multimodal, handles large files via Files API)
  Tier 3 — Gemini Lite     (fallback when Gemini quota is hit)

Provider selection logic
------------------------
1.  If file <= 25 MB AND GROQ_API_KEY is set  →  try Groq first
2.  If Groq fails (missing key, rate-limit, unsupported format, >25 MB)
    →  fall through to Gemini
3.  If Gemini returns rate-limit error  →  fall through to Gemini Lite
4.  If ALL providers fail  →  return a clear "Audio STT Failed: …" string

This keeps the multimodal work (large files, video containers) on Gemini
while giving Groq first crack at everyday mp3/wav/m4a uploads.
"""

import os
import time
import logging
from pathlib import Path

from services.gemini_service import GeminiService, GeminiServiceError

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Groq Whisper hard limit: 25 MB
GROQ_MAX_BYTES = 25 * 1024 * 1024

# Gemini inline limit: 10 MB; above this use the Files API
GEMINI_INLINE_LIMIT_BYTES = 10 * 1024 * 1024

# MIME types that Groq Whisper accepts
GROQ_SUPPORTED_MIMES = {
    "audio/mpeg",           # .mp3
    "audio/mp4",            # .mp4 audio
    "audio/mpga",           # .mpga
    "audio/m4a",            # .m4a
    "audio/wav",            # .wav
    "audio/x-wav",          # .wav (alternative)
    "audio/webm",           # .webm audio
    "audio/ogg",            # .ogg
    "audio/flac",           # .flac
    "audio/x-flac",         # .flac (alternative)
    "video/mp4",            # .mp4 video (Groq extracts audio track)
    "video/mpeg",           # .mpeg
    "video/webm",           # .webm video
}

# Gemini transcription prompt
_TRANSCRIBE_PROMPT = (
    "Transcribe this audio clip completely and accurately. "
    "Return only the transcription text, no timestamps or annotations."
)


# ── Helper ────────────────────────────────────────────────────────────────────

def _estimate_meta(transcript: str) -> dict:
    """Return a metadata dict estimated from transcript word count."""
    word_count = len(transcript.split())
    estimated_duration_sec = round((word_count / 130) * 60)  # ~130 wpm average
    return {
        "duration_seconds": estimated_duration_sec,
        "word_count": word_count,
        "language": "auto",
    }


# ── Provider implementations ──────────────────────────────────────────────────

def _transcribe_groq(file_path: str, mime_type: str, groq_key: str) -> str:
    """
    Transcribe audio using Groq's Whisper API.

    Raises:
        Exception — on any failure (caller decides whether to fall through).
    """
    from groq import Groq  # pip install groq

    file_size = os.path.getsize(file_path)
    if file_size > GROQ_MAX_BYTES:
        raise ValueError(
            f"File size {file_size / (1024*1024):.1f} MB exceeds Groq's 25 MB limit."
        )

    if mime_type not in GROQ_SUPPORTED_MIMES:
        raise ValueError(
            f"MIME type '{mime_type}' is not supported by Groq Whisper. "
            f"Supported: {', '.join(sorted(GROQ_SUPPORTED_MIMES))}"
        )

    client = Groq(api_key=groq_key, timeout=120)
    filename = Path(file_path).name

    logger.info("[Audio STT] Groq: uploading %s (%.1f MB)", filename, file_size / (1024 * 1024))

    with open(file_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",   # fast + accurate; fallback model available
            file=(filename, f, mime_type),
            response_format="text",
        )

    # response_format="text" → returns a plain string, not an object
    if isinstance(transcription, str):
        return transcription.strip()

    # response_format="json" → object with .text
    text = getattr(transcription, "text", "") or ""
    return text.strip()


def _transcribe_gemini(
    file_path: str,
    mime_type: str,
    gemini_key: str,
    model_name: str = "gemini-2.5-flash",
) -> str:
    """
    Transcribe audio/video using Gemini multimodal API.
    Uses inline bytes for small files and the Files API for large ones.

    Raises:
        GeminiServiceError — on API failures.
    """
    file_size = os.path.getsize(file_path)
    logger.info(
        "[Audio STT] Gemini: transcribing %s (%.1f MB) via %s",
        Path(file_path).name,
        file_size / (1024 * 1024),
        model_name,
    )

    GeminiService.configure(gemini_key)

    if file_size > GEMINI_INLINE_LIMIT_BYTES:
        # Large file — use Files API
        logger.info("[Audio STT] Gemini Files API: uploading…")
        uploaded = GeminiService.upload_file(file_path, mime_type=mime_type)

        # Poll until ready
        for _ in range(20):  # max ~60 s
            if uploaded.state.name != "PROCESSING":
                break
            logger.info("[Audio STT] Gemini: waiting for file processing…")
            time.sleep(3)
            uploaded = GeminiService.get_file(uploaded.name)

        if uploaded.state.name == "FAILED":
            raise GeminiServiceError(
                "Gemini file processing failed.", code="processing_failed"
            )

        content_part = uploaded
    else:
        # Small file — inline bytes
        with open(file_path, "rb") as f:
            content_part = {"mime_type": mime_type, "data": f.read()}

    response = GeminiService.generate_content(
        [content_part, _TRANSCRIBE_PROMPT],
        api_key=gemini_key,
        model_name=model_name,
    )
    return (response.text or "").strip()


# ── Public interface ──────────────────────────────────────────────────────────

class AudioTranscriber:
    """
    Transcribes audio/video files via Groq Whisper (primary) → Gemini (fallback).

    Returns
    -------
    (transcript: str, meta: dict)
        On success: transcript is the full text, meta has duration_seconds etc.
        On failure: transcript starts with "Audio STT Failed:", meta is {}.
    """

    @staticmethod
    def transcribe(
        file_path: str,
        mime_type: str,
        gemini_key: str,
        model_name: str = "gemini-2.5-flash",
    ) -> tuple[str, dict]:

        file_size = os.path.getsize(file_path)
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()

        logger.info(
            "[Audio STT] file=%.1f MB  mime=%s  groq_key_present=%s  gemini_key_present=%s",
            file_size / (1024 * 1024),
            mime_type,
            bool(groq_key),
            bool(gemini_key),
        )

        # ── Tier 1: Groq Whisper ────────────────────────────────────────────
        groq_skip_reason = None
        if not groq_key:
            groq_skip_reason = "GROQ_API_KEY not set"
        elif file_size > GROQ_MAX_BYTES:
            groq_skip_reason = f"file too large ({file_size/(1024*1024):.1f} MB > 25 MB limit)"
        elif mime_type not in GROQ_SUPPORTED_MIMES:
            groq_skip_reason = f"unsupported MIME type for Groq: {mime_type}"

        if groq_skip_reason:
            logger.info("[Audio STT] Skipping Groq — %s. Trying Gemini.", groq_skip_reason)
        else:
            try:
                logger.info("[Audio STT] Tier 1 — trying Groq Whisper…")
                transcript = _transcribe_groq(file_path, mime_type, groq_key)
                if transcript:
                    logger.info(
                        "[Audio STT] ✅ Groq succeeded (%d words)", len(transcript.split())
                    )
                    return transcript, _estimate_meta(transcript)
                logger.warning("[Audio STT] Groq returned empty transcript — trying Gemini.")
            except Exception as groq_err:
                logger.warning(
                    "[Audio STT] Groq failed: %s — falling through to Gemini.", groq_err
                )

        # ── Tier 2: Gemini ──────────────────────────────────────────────────
        if not gemini_key:
            logger.error("[Audio STT] No Gemini API key — cannot fall back.")
            return (
                "Audio STT Failed: Gemini API key is invalid or missing. "
                "Please verify your GEMINI_API_KEY configuration.",
                {},
            )

        try:
            logger.info("[Audio STT] Tier 2 — trying Gemini (%s)…", model_name)
            transcript = _transcribe_gemini(file_path, mime_type, gemini_key, model_name)
            if transcript:
                logger.info(
                    "[Audio STT] ✅ Gemini succeeded (%d words)", len(transcript.split())
                )
                return transcript, _estimate_meta(transcript)
            logger.warning("[Audio STT] Gemini returned empty transcript — trying Gemini Lite.")
        except GeminiServiceError as gem_err:
            if gem_err.code == "invalid_api_key":
                logger.error("[Audio STT] Gemini API key invalid: %s", gem_err)
                return (
                    f"Audio STT Failed: {GeminiService.friendly_error_message(gem_err)}",
                    {},
                )
            # Rate limit or other — fall through to Lite
            logger.warning(
                "[Audio STT] Gemini (%s) error: %s — trying Gemini Lite.", model_name, gem_err
            )
        except Exception as e:
            logger.warning("[Audio STT] Gemini unexpected error: %s — trying Gemini Lite.", e)

        # ── Tier 3: Gemini Lite ─────────────────────────────────────────────
        lite_model = "gemini-2.5-flash-lite"
        try:
            logger.info("[Audio STT] Tier 3 — trying Gemini Lite (%s)…", lite_model)
            transcript = _transcribe_gemini(file_path, mime_type, gemini_key, lite_model)
            if transcript:
                logger.info(
                    "[Audio STT] ✅ Gemini Lite succeeded (%d words)", len(transcript.split())
                )
                return transcript, _estimate_meta(transcript)
        except GeminiServiceError as gem_lite_err:
            logger.error("[Audio STT] Gemini Lite also failed: %s", gem_lite_err)
            return (
                f"Audio STT Failed: {GeminiService.friendly_error_message(gem_lite_err)}",
                {},
            )
        except Exception as e:
            logger.error("[Audio STT] All providers failed. Last error: %s", e)

        return (
            "Audio STT Failed: All transcription providers (Groq Whisper + Gemini) failed. "
            "Please check your API keys and ensure the audio file is valid.",
            {},
        )