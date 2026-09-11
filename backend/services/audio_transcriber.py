"""
Audio Speech-to-Text transcriber with robust local-first pipeline.

Strategy:
  Tier 1 — Local faster-whisper with ffmpeg preprocessing
            (handles webm/m4a/mp3/ogg/wav → clean 16kHz mono PCM)
  Tier 2 — Groq Whisper   (ONLINE mode only, fast, up to 25 MB)
  Tier 3 — Gemini          (ONLINE mode only, handles large files)

Key design decisions:
  - ALL audio is preprocessed through ffmpeg → 16kHz mono WAV before Whisper.
    This fixes the critical VAD bug where Silero VAD removes 100% of speech
    from raw webm/m4a containers with non-standard sample rates.
  - Multi-pass transcription: permissive VAD → no VAD → forced English → greedy.
  - In OFFLINE mode, cloud providers are NEVER called, even on empty transcript.
  - Model is loaded once via lru_cache — no per-request loading.
"""

import os
import time
import shutil
import subprocess
import tempfile
import logging
from functools import lru_cache
from pathlib import Path

from services.gemini_service import GeminiService, GeminiServiceError
from core.config import get_settings

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

GROQ_MAX_BYTES = 25 * 1024 * 1024
GEMINI_INLINE_LIMIT_BYTES = 10 * 1024 * 1024

GROQ_SUPPORTED_MIMES = {
    "audio/mpeg", "audio/mp4", "audio/mpga", "audio/m4a",
    "audio/wav", "audio/x-wav", "audio/webm", "audio/ogg",
    "audio/flac", "audio/x-flac",
    "video/mp4", "video/mpeg", "video/webm",
}

_TRANSCRIBE_PROMPT = (
    "Transcribe this audio clip completely and accurately. "
    "Return only the transcription text, no timestamps or annotations."
)


# ── ffmpeg Preprocessing ──────────────────────────────────────────────────────

def _ffmpeg_to_wav(input_path: str) -> str:
    """Convert any audio/video to clean 16kHz mono PCM WAV using ffmpeg.

    This is critical: faster-whisper's Silero VAD expects 16kHz mono PCM.
    Raw webm/m4a/ogg containers often have 48kHz stereo with metadata that
    confuses VAD, causing it to mark 100% of the audio as silence.

    Returns path to the temporary WAV file (caller must clean up).
    """
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        logger.warning("[Audio STT] ffmpeg not found — using raw file (VAD may fail)")
        return input_path

    # Create temp WAV in the same directory to avoid cross-filesystem issues
    parent = Path(input_path).parent
    wav_path = str(parent / f"whisper_{Path(input_path).stem}_{os.getpid()}.wav")

    cmd = [
        ffmpeg_bin,
        "-y",                   # overwrite
        "-i", input_path,       # input
        "-vn",                  # drop video
        "-ac", "1",             # mono
        "-ar", "16000",         # 16 kHz
        "-sample_fmt", "s16",   # 16-bit signed PCM
        "-f", "wav",            # output format
        wav_path,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.warning("[Audio STT] ffmpeg failed (rc=%d): %s", result.returncode, result.stderr[:500])
            return input_path  # fallback to raw file

        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 44:
            wav_size = os.path.getsize(wav_path)
            orig_size = os.path.getsize(input_path)
            logger.info(
                "[Audio STT] ffmpeg converted: %s → %s (%.1f KB → %.1f KB, 16kHz mono PCM)",
                Path(input_path).name, Path(wav_path).name,
                orig_size / 1024, wav_size / 1024,
            )
            return wav_path
        else:
            logger.warning("[Audio STT] ffmpeg output is empty or missing")
            return input_path
    except subprocess.TimeoutExpired:
        logger.warning("[Audio STT] ffmpeg timed out after 120s")
        return input_path
    except Exception as e:
        logger.warning("[Audio STT] ffmpeg error: %s", e)
        return input_path


# ── Helper ────────────────────────────────────────────────────────────────────

def _estimate_meta(transcript: str, provider: str, speech_duration: float = 0.0) -> dict:
    """Return metadata dict from transcript and optional speech duration."""
    word_count = len(transcript.split())
    duration_sec = round(speech_duration) if speech_duration > 0 else round((word_count / 130) * 60)
    return {
        "duration_seconds": duration_sec,
        "word_count": word_count,
        "language": "auto",
        "provider": provider,
    }


def _clean_transcript(text: str) -> str:
    """Filter out empty or repetitive hallucination strings."""
    if not text or not text.strip():
        return ""
    words = text.strip().split()
    if len(words) >= 6 and len(set(words)) == 1:
        return ""
    return text.strip()


# ── Local Whisper Model (singleton) ───────────────────────────────────────────

@lru_cache(maxsize=1)
def _local_model():
    """Load the faster-whisper model exactly once.
    Uses local_files_only=True to prevent any HuggingFace network requests."""
    from faster_whisper import WhisperModel

    settings = get_settings()
    logger.info(
        "[Audio STT] Loading faster-whisper model='%s' device='%s' compute='%s' local_files_only=True",
        settings.whisper_model, settings.whisper_device, settings.whisper_compute_type,
    )
    model = WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        local_files_only=True,
    )
    logger.info("[Audio STT] ✅ faster-whisper model loaded successfully")
    return model


def _transcribe_local(file_path: str) -> tuple[str, float]:
    """Transcribe audio locally with faster-whisper.

    Strategy:
      Pass 1: Permissive VAD + beam search
      Pass 2: VAD disabled + beam search (fixes Silero VAD dropping speech)
      Pass 3: Forced English (language='en') + no VAD (fixes false 'nn'/uncommon language detection)
      Pass 4: Greedy decode (beam=1)

    Returns (transcript_text, speech_duration_seconds).
    """
    model = _local_model()

    # ── Pass 1: With permissive VAD ──
    logger.info("[Audio STT] Pass 1: beam_size=5, vad_filter=True (permissive)")
    try:
        segments, info = model.transcribe(
            file_path,
            beam_size=5,
            vad_filter=True,
            vad_parameters={
                "min_speech_duration_ms": 100,
                "max_speech_duration_s": float("inf"),
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 400,
                "threshold": 0.25,
            },
            condition_on_previous_text=False,
            no_speech_threshold=0.75,
        )
        parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
        transcript = _clean_transcript(" ".join(parts))
        speech_dur = getattr(info, "duration", 0) or 0
        lang = getattr(info, "language", "?")
        lang_prob = getattr(info, "language_probability", 0)
        logger.info(
            "[Audio STT] Pass 1: transcript=%d chars, dur=%.1fs, lang=%s (prob=%.2f)",
            len(transcript), speech_dur, lang, lang_prob,
        )
        if transcript and lang_prob >= 0.4 and lang not in {"nn", "jw", "sn", "la", "haw"}:
            return transcript, speech_dur
    except Exception as e:
        logger.warning("[Audio STT] Pass 1 failed: %s", e)

    # ── Pass 2: WITHOUT VAD (the critical fix for VAD-kills-all-speech) ──
    logger.info("[Audio STT] Pass 2: beam_size=5, vad_filter=False")
    try:
        segments, info = model.transcribe(
            file_path,
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.85,
            compression_ratio_threshold=2.4,
            temperature=[0.0, 0.2, 0.4],
        )
        parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
        transcript = _clean_transcript(" ".join(parts))
        speech_dur = getattr(info, "duration", 0) or 0
        lang = getattr(info, "language", "?")
        lang_prob = getattr(info, "language_probability", 0)
        logger.info(
            "[Audio STT] Pass 2: transcript=%d chars, dur=%.1fs, lang=%s (prob=%.2f)",
            len(transcript), speech_dur, lang, lang_prob,
        )
        if transcript and lang not in {"nn", "jw", "sn", "la", "haw"}:
            return transcript, speech_dur
    except Exception as e:
        logger.warning("[Audio STT] Pass 2 failed: %s", e)

    # ── Pass 3: Forced English (language='en'), no VAD ──
    logger.info("[Audio STT] Pass 3: forced language='en', vad_filter=False")
    try:
        segments, info = model.transcribe(
            file_path,
            language="en",
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.9,
            temperature=0.0,
        )
        parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
        transcript = _clean_transcript(" ".join(parts))
        speech_dur = getattr(info, "duration", 0) or 0
        logger.info("[Audio STT] Pass 3: transcript=%d chars, dur=%.1fs", len(transcript), speech_dur)
        if transcript:
            return transcript, speech_dur
    except Exception as e:
        logger.warning("[Audio STT] Pass 3 failed: %s", e)

    # ── Pass 4: Greedy decode (beam_size=1) ──
    logger.info("[Audio STT] Pass 4: beam_size=1 (greedy), vad_filter=False")
    try:
        segments, info = model.transcribe(
            file_path,
            beam_size=1,
            vad_filter=False,
            temperature=0.0,
        )
        parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
        transcript = _clean_transcript(" ".join(parts))
        speech_dur = getattr(info, "duration", 0) or 0
        if transcript:
            return transcript, speech_dur
    except Exception as e:
        logger.warning("[Audio STT] Pass 4 failed: %s", e)

    return "", 0.0


# ── Cloud providers (ONLINE mode only) ────────────────────────────────────────

def _transcribe_groq(file_path: str, mime_type: str, groq_key: str) -> str:
    """Transcribe via Groq Whisper API. Raises on failure."""
    from groq import Groq

    file_size = os.path.getsize(file_path)
    if file_size > GROQ_MAX_BYTES:
        raise ValueError(f"File size {file_size / (1024*1024):.1f} MB exceeds Groq's 25 MB limit.")
    if mime_type not in GROQ_SUPPORTED_MIMES:
        raise ValueError(f"MIME type '{mime_type}' not supported by Groq Whisper.")

    client = Groq(api_key=groq_key, timeout=120)
    filename = Path(file_path).name
    logger.info("[Audio STT] Groq: uploading %s (%.1f MB)", filename, file_size / (1024 * 1024))

    with open(file_path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            model="whisper-large-v3-turbo",
            file=(filename, f, mime_type),
            response_format="text",
        )

    if isinstance(transcription, str):
        return transcription.strip()
    text = getattr(transcription, "text", "") or ""
    return text.strip()


def _transcribe_gemini(
    file_path: str, mime_type: str, gemini_key: str,
    model_name: str = "gemini-2.5-flash",
) -> str:
    """Transcribe via Gemini multimodal API. Raises on failure."""
    file_size = os.path.getsize(file_path)
    logger.info("[Audio STT] Gemini: transcribing %s (%.1f MB) via %s",
                Path(file_path).name, file_size / (1024 * 1024), model_name)

    GeminiService.configure(gemini_key)

    if file_size > GEMINI_INLINE_LIMIT_BYTES:
        logger.info("[Audio STT] Gemini Files API: uploading…")
        uploaded = GeminiService.upload_file(file_path, mime_type=mime_type)
        for _ in range(20):
            if uploaded.state.name != "PROCESSING":
                break
            logger.info("[Audio STT] Gemini: waiting for file processing…")
            time.sleep(3)
            uploaded = GeminiService.get_file(uploaded.name)
        if uploaded.state.name == "FAILED":
            raise GeminiServiceError("Gemini file processing failed.", code="processing_failed")
        content_part = uploaded
    else:
        with open(file_path, "rb") as f:
            content_part = {"mime_type": mime_type, "data": f.read()}

    response = GeminiService.generate_content(
        [content_part, _TRANSCRIBE_PROMPT],
        api_key=gemini_key, model_name=model_name,
    )
    return (response.text or "").strip()


# ── Public interface ──────────────────────────────────────────────────────────

class AudioTranscriber:
    """Transcribes audio/video files.

    Returns (transcript: str, meta: dict).
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
        settings = get_settings()
        is_offline = settings.llm_mode == "offline"
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()

        logger.info(
            "[Audio STT] file=%.1f MB  mime=%s  mode=%s  groq_key=%s  gemini_key=%s",
            file_size / (1024 * 1024), mime_type, settings.llm_mode,
            bool(groq_key), bool(gemini_key),
        )

        # ── Step 1: ffmpeg preprocessing → clean 16kHz mono PCM WAV ─────────
        wav_path = _ffmpeg_to_wav(file_path)
        wav_is_temp = wav_path != file_path

        try:
            # ── Step 2: Local faster-whisper transcription ──────────────────
            try:
                logger.info("[Audio STT] Tier 1: local faster-whisper (model='%s', device='%s')",
                            settings.whisper_model, settings.whisper_device)
                transcript, speech_dur = _transcribe_local(wav_path)

                if transcript:
                    logger.info(
                        "[Audio STT] ✅ Local faster-whisper succeeded: %d words, %.1fs speech",
                        len(transcript.split()), speech_dur,
                    )
                    return transcript, _estimate_meta(transcript, "faster-whisper", speech_dur)
                else:
                    logger.warning("[Audio STT] Local faster-whisper returned empty transcript after all passes")

            except Exception as local_err:
                logger.warning("[Audio STT] Local faster-whisper failed: %s: %s",
                               type(local_err).__name__, local_err)

            # ── OFFLINE mode: stop here, never call cloud ───────────────────
            if is_offline:
                logger.error(
                    "[Audio STT] LLM_MODE=offline. Local STT produced empty transcript. "
                    "NOT falling back to cloud providers."
                )
                return (
                    "Audio STT Failed: Local faster-whisper could not detect intelligible speech in the audio file. "
                    "No cloud fallback is allowed in OFFLINE mode.",
                    {},
                )

            # ── ONLINE mode: try cloud providers ────────────────────────────
            logger.info("[Audio STT] ONLINE mode — trying cloud providers")

            # Tier 2: Groq Whisper
            groq_skip = None
            if not groq_key:
                groq_skip = "GROQ_API_KEY not set"
            elif file_size > GROQ_MAX_BYTES:
                groq_skip = f"file too large ({file_size/(1024*1024):.1f} MB)"
            elif mime_type not in GROQ_SUPPORTED_MIMES:
                groq_skip = f"unsupported MIME: {mime_type}"

            if groq_skip:
                logger.info("[Audio STT] Skipping Groq — %s", groq_skip)
            else:
                try:
                    logger.info("[Audio STT] Tier 2: Groq Whisper")
                    transcript = _transcribe_groq(file_path, mime_type, groq_key)
                    if transcript:
                        logger.info("[Audio STT] ✅ Groq succeeded (%d words)", len(transcript.split()))
                        return transcript, _estimate_meta(transcript, "groq-whisper")
                    logger.warning("[Audio STT] Groq returned empty transcript")
                except Exception as groq_err:
                    logger.warning("[Audio STT] Groq failed: %s", groq_err)

            # Tier 3: Gemini
            if not gemini_key:
                return ("Audio STT Failed: No cloud API keys available for fallback.", {})

            try:
                logger.info("[Audio STT] Tier 3: Gemini (%s)", model_name)
                transcript = _transcribe_gemini(file_path, mime_type, gemini_key, model_name)
                if transcript:
                    logger.info("[Audio STT] ✅ Gemini succeeded (%d words)", len(transcript.split()))
                    return transcript, _estimate_meta(transcript, "gemini")
            except GeminiServiceError as gem_err:
                if gem_err.code == "invalid_api_key":
                    return (f"Audio STT Failed: {GeminiService.friendly_error_message(gem_err)}", {})
                logger.warning("[Audio STT] Gemini error: %s", gem_err)
            except Exception as e:
                logger.warning("[Audio STT] Gemini unexpected error: %s", e)

            # Tier 4: Gemini Lite
            try:
                lite_model = "gemini-2.5-flash-lite"
                logger.info("[Audio STT] Tier 4: Gemini Lite (%s)", lite_model)
                transcript = _transcribe_gemini(file_path, mime_type, gemini_key, lite_model)
                if transcript:
                    logger.info("[Audio STT] ✅ Gemini Lite succeeded (%d words)", len(transcript.split()))
                    return transcript, _estimate_meta(transcript, "gemini-lite")
            except Exception as e:
                logger.error("[Audio STT] All cloud providers failed. Last: %s", e)

            return (
                "Audio STT Failed: All transcription providers failed. "
                "Please check your audio file and API keys.",
                {},
            )

        finally:
            # Clean up temp WAV file
            if wav_is_temp and os.path.exists(wav_path):
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass