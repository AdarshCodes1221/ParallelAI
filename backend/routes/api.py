import os
import json
import asyncio
import logging
from datetime import datetime
from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional

from agent.workflow import AgentWorkflow
from services.pdf_parser import PDFParser
from services.ocr_service import OCRService
from services.audio_transcriber import AudioTranscriber
from services.youtube_fetcher import YouTubeFetcher
from services.summarizer import SummarizerService
from services.sentiment import SentimentService
from services.code_analyzer import CodeAnalyzerService
from services.gemini_service import GeminiService, GeminiServiceError

logger = logging.getLogger(__name__)

router = APIRouter()


class URLRequest(BaseModel):
    url: str


class TextRequest(BaseModel):
    text: str


def _get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured on server.")
    return key


def _get_groq_api_key() -> str:
    return os.environ.get("GROQ_API_KEY", "")


def _save_upload(file: UploadFile) -> str:
    """Save an uploaded file to temp dir and return its path."""
    temp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "temp_uploads")
    os.makedirs(temp_dir, exist_ok=True)
    path = os.path.join(temp_dir, file.filename)
    return path


# ─────────────────────────────────────────────────────────────
# Main Agent SSE Endpoint
# ─────────────────────────────────────────────────────────────
@router.post("/agent")
async def run_agent(
    query: str = Form(default=""),
    model: str = Form(default="models/gemini-2.5-flash"),
    files: List[UploadFile] = File(default=[])
):
    temp_dir = os.path.join(os.path.dirname(__file__), "..", "..", "temp_uploads")
    os.makedirs(temp_dir, exist_ok=True)

    saved_files = []
    for f in files:
        if f.filename:
            path = os.path.join(temp_dir, f.filename)
            with open(path, "wb") as buf:
                buf.write(await f.read())
            saved_files.append({"path": path, "filename": f.filename, "mime_type": f.content_type})

    # Require GEMINI API key for OCR — surface configuration errors early
    api_key = _get_api_key()
    model_name = model.replace("models/", "") if model else "gemini-2.5-flash"

    async def event_stream():
        try:
            result = await AgentWorkflow.execute(query, saved_files, api_key, model_name)

            def estimate_cost(input_text: str, output_text: str | None = None):
                input_tokens = max(10, len(input_text) // 4)
                output_tokens = max(50, len(output_text or '') // 4)
                estimated_cost_usd = round((input_tokens + output_tokens) * 0.0000004, 6)
                return {
                    'provider': 'Gemini Estimate',
                    'input_tokens_est': input_tokens,
                    'output_tokens_est': output_tokens,
                    'estimated_cost_usd': estimated_cost_usd,
                }

            formatted_plan = [
                {
                  'step': i + 1,
                  'tool': p['tool'],
                  'started_at': datetime.utcnow().isoformat() + 'Z',
                }
                for i, p in enumerate(result['plan'])
            ]
            extracted_files = [
                {'filename': tool, 'content': out}
                for tool, out in result['tool_results'].items() if out
            ]

            yield f"data: {json.dumps({'type': 'init', 'cost': estimate_cost(query), 'extracted_texts': extracted_files, 'plan': formatted_plan})}\n\n"

            trace_data = []
            for i, p in enumerate(result['plan']):
                tool = p['tool']
                out = result['tool_results'].get(tool, '')
                trace_data.append({
                    'step': i + 1,
                    'tool': tool,
                    'execution_duration_sec': 1.0,
                    'output_preview': (out[:150] + '...') if len(out) > 150 else out,
                })
            yield f"data: {json.dumps({'type': 'trace', 'trace': trace_data})}\n\n"

            final_text = result['final_response']
            chunk_size = 10
            for i in range(0, len(final_text), chunk_size):
                yield f"data: {json.dumps({'type': 'token', 'token': final_text[i:i + chunk_size]})}\n\n"
                await asyncio.sleep(0.01)

            yield f"data: {json.dumps({'type': 'cost_update', 'cost': estimate_cost(query, final_text)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            message = (
                GeminiService.friendly_error_message(e)
                if isinstance(e, GeminiServiceError)
                else "An internal error occurred while processing your request."
            )
            yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ─────────────────────────────────────────────────────────────
# Individual Task Endpoints (FIXED — no longer mock stubs)
# ─────────────────────────────────────────────────────────────

@router.post("/pdf")
async def parse_pdf(file: UploadFile = File(...)):
    """Extract text from an uploaded PDF (digital or scanned)."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    path = _save_upload(file)
    with open(path, "wb") as buf:
        buf.write(await file.read())

    try:
        logger = __import__('logging').getLogger(__name__)
        logger.info(f"/api/pdf called for {file.filename}; saved to {path}")
        text = PDFParser.extract_text(path, api_key=api_key if api_key else None, model_name="gemini-2.5-flash")
        is_error = isinstance(text, str) and text.startswith("⚠️")
        return {
            "status": "error" if is_error else "ok",
            "filename": file.filename,
            "text": text,
            "char_count": len(text) if isinstance(text, str) else 0
        }
    except Exception as e:
        import traceback
        traceback_str = traceback.format_exc()
        logger = __import__('logging').getLogger(__name__)
        logger.exception(f"/api/pdf processing failed for {file.filename}: {e}\n{traceback_str}")
        raise HTTPException(status_code=500, detail=f"PDF processing error: {e}")


@router.post("/ocr")
async def ocr_image(file: UploadFile = File(...)):
    """Extract text from an uploaded image using OCR."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    path = _save_upload(file)
    with open(path, "wb") as buf:
        buf.write(await file.read())

    logger.info(
        "/api/ocr called: GEMINI_KEY_PRESENT=%s, KEY_PREFIX=%s, FILENAME=%s, MIMETYPE=%s",
        bool(api_key),
        (api_key[:10] + "...") if api_key else "N/A",
        file.filename,
        file.content_type,
    )

    text, confidence = OCRService.extract_text(
        path, file.content_type, gemini_key=api_key if api_key else None, model_name="gemini-2.5-flash"
    )
    return {
        "status": "ok",
        "filename": file.filename,
        "text": text,
        "confidence": confidence
    }


@router.post("/audio")
@router.post("/audiostt")
async def transcribe_audio(file: UploadFile = File(...)):
    """Transcribe an uploaded audio or video file (MP3/WAV/M4A/WEBM)."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not file.content_type.startswith(("audio/", "video/")):
        raise HTTPException(
            status_code=400,
            detail="Unsupported media type. Upload an audio or video file for transcription.",
        )

    path = _save_upload(file)
    with open(path, "wb") as buf:
        buf.write(await file.read())

    transcript, meta = AudioTranscriber.transcribe(
        path, file.content_type, gemini_key=api_key if api_key else None, model_name="gemini-2.5-flash"
    )
    return {
        "status": "ok",
        "filename": file.filename,
        "transcript": transcript,
        "meta": meta
    }


@router.post("/youtube")
async def fetch_youtube(req: URLRequest):
    """Fetch transcript from a YouTube URL."""
    transcript = YouTubeFetcher.fetch_transcript(req.url)
    is_error = transcript.startswith("Failed") or transcript.startswith("No valid")
    return {
        "status": "error" if is_error else "ok",
        "url": req.url,
        "transcript": transcript
    }


@router.post("/summary")
async def summarize(req: TextRequest):
    """Summarize provided text into 1-line + 3 bullets + 5-sentence format."""
    groq_key = _get_groq_api_key()
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    try:
        summary = SummarizerService.summarize(
            req.text,
            groq_api_key=groq_key,
            gemini_api_key=gemini_key,
            model_name=None,
        )
        return {"status": "ok", "summary": summary}
    except Exception as e:
        logger.exception("Summary endpoint failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/sentiment")
async def analyze_sentiment(req: TextRequest):
    """Analyze sentiment of provided text."""
    groq_key = _get_groq_api_key()
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    try:
        analysis = SentimentService.analyze(
            req.text,
            groq_api_key=groq_key,
            gemini_api_key=gemini_key,
            model_name=None,
        )
        return {"status": "ok", "analysis": analysis}
    except Exception as e:
        logger.exception("Sentiment endpoint failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/code-analysis")
async def analyze_code(req: TextRequest):
    """Explain code, detect bugs, and return time complexity."""
    groq_key = _get_groq_api_key()
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    try:
        analysis = CodeAnalyzerService.analyze(
            req.text,
            groq_api_key=groq_key,
            gemini_api_key=gemini_key,
            model_name=None,
        )
        return {"status": "ok", "analysis": analysis}
    except Exception as e:
        logger.exception("Code analysis endpoint failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Simple file upload endpoint — returns metadata."""
    return {"status": "uploaded", "filename": file.filename, "content_type": file.content_type}


@router.get("/health")
def health_check():
    return {"status": "ok"}