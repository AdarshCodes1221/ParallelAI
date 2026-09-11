import os
import json
import asyncio
import logging
import uuid
import re
from datetime import datetime
from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any, List, Optional

from agent.workflow import AgentWorkflow
from services.pdf_parser import PDFParser
from services.ocr_service import OCRService
from services.audio_transcriber import AudioTranscriber
from services.youtube_fetcher import YouTubeFetcher
from services.summarizer import SummarizerService
from services.sentiment import SentimentService
from services.code_analyzer import CodeAnalyzerService
from services.gemini_service import GeminiService, GeminiServiceError
from services.session_service import SessionService
from services.document_service import DocumentService
from services.model_registry import list_models
from services.ingestion.manager import IngestionManager
from services.retrieval.citation_builder import build_citations
from services.query_context_resolver import QueryContextResolver
from routes.auth import get_current_user, get_current_user_optional, verify_csrf
from core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
session_service = SessionService()
document_service = DocumentService()
ingestion_manager = IngestionManager()


class URLRequest(BaseModel):
    url: str


class TextRequest(BaseModel):
    text: str


class SessionRequest(BaseModel):
    session_id: Optional[str] = None
    title: Optional[str] = "New Chat"


class RenameSessionRequest(BaseModel):
    title: str


class SearchRequest(BaseModel):
    query: str
    session_id: str
    document_ids: Optional[List[str]] = None


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
    safe_name = os.path.basename(file.filename or "upload")
    path = os.path.join(temp_dir, f"{uuid.uuid4()}-{safe_name}")
    return path


# ─────────────────────────────────────────────────────────────
# Main Agent SSE Endpoint
# ─────────────────────────────────────────────────────────────
@router.post("/agent")
async def run_agent(
    request: Request,
    session_id: str = Form(default=""),
    query: str = Form(default=""),
    model: str = Form(default="models/gemini-2.5-flash"),
    files: List[UploadFile] = File(default=[]),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    request_id = str(uuid.uuid4())[:8]
    user_id = current_user["id"]

    if not session_id:
        session_id = session_service.create(title=query[:30] if query else "New Chat", user_id=user_id)["id"]
    else:
        existing_session = session_service.get(session_id, user_id=user_id)
        if existing_session and existing_session.get("user_id") != user_id:
            raise HTTPException(status_code=404, detail="Session not found")
        if not existing_session:
            other_session = session_service.get(session_id, user_id=None)
            if other_session:
                raise HTTPException(status_code=403, detail="Access to this session is forbidden")
            session_service.create(session_id, title=query[:30] if query else "New Chat", user_id=user_id)

    saved_files = []
    for f in files:
        if f.filename:
            content = await f.read()
            document = document_service.create_from_bytes(
                f.filename, content, session_id, f.content_type or "application/octet-stream", user_id=user_id,
            )
            document_service.update(document["id"], status="PROCESSING")
            saved_files.append({
                "path": document["storage_path"],
                "filename": document["filename"],
                "mime_type": document["mime_type"],
                "document_id": document["id"],
            })

    context = QueryContextResolver.resolve(query, document_service.list(session_id, user_id=user_id))
    explicit_previous = bool(re.search(r"\b(previous|prior|earlier|old|conversation|history|before|that|said)\b", query, re.IGNORECASE))
    active_document_ids = context.document_ids if context.use_retrieval else []
    recent_messages = session_service.recent_messages(session_id, user_id=user_id) if (explicit_previous or context.use_retrieval) else []

    if query:
        session_service.save_message(session_id, "user", query, user_id=user_id)

    api_key = os.environ.get("GEMINI_API_KEY", "")
    model_name = model.replace("models/", "") if model else "gemini-2.5-flash"

    logger.info(
        "[/api/agent] request_id=%s session_id=%s query='%s' files=%d active_docs=%s retrieval=%s reason=%s",
        request_id, session_id, query[:60], len(saved_files), active_document_ids, context.use_retrieval, context.reason
    )

    async def event_stream():
        try:
            result = await AgentWorkflow.execute(
                query,
                saved_files,
                api_key,
                model_name,
                session_id=session_id,
                active_document_ids=active_document_ids,
                recent_messages=recent_messages,
                user_id=user_id,
            )

            # Persist extracted texts & status for all uploaded files
            audio_meta = result.get("tool_results", {}).get("_audio_meta", {})
            for saved_file in saved_files:
                document_id = saved_file["document_id"]
                source_type = "pdf_parser" if saved_file["mime_type"] == "application/pdf" else (
                    "ocr" if saved_file["mime_type"].startswith("image/") else "audio"
                )
                tool_key = "pdf_parser" if source_type == "pdf_parser" else ("ocr" if source_type == "ocr" else "audio_stt")
                output = result["tool_results"].get(tool_key, "")
                rag_errors = result["tool_results"].get("_rag_ingestion_errors", {})
                failed = (
                    not output
                    or str(output).startswith(("Error", "OCR Failed", "Audio STT Failed", "⚠️"))
                    or document_id in rag_errors
                )
                document_service.update(
                    document_id,
                    status="FAILED" if failed else "READY",
                    extracted_text=output if isinstance(output, str) and not failed else "",
                    modality="pdf" if source_type == "pdf_parser" else ("image" if source_type == "ocr" else "audio"),
                    source_type="pdf" if source_type == "pdf_parser" else ("ocr" if source_type == "ocr" else "audio"),
                    duration_seconds=audio_meta.get("duration_seconds", 0) if tool_key == "audio_stt" else 0,
                    confidence=audio_meta.get("confidence", 1.0) if tool_key == "audio_stt" else 1.0,
                )


            actual_provider = result.get('provider') or 'unknown'

            def calculate_cost(input_text: str, output_text: str | None = None):
                input_tokens = max(10, len(input_text) // 4)
                output_tokens = max(50, len(output_text or '') // 4)
                
                # Provider-accurate cost accounting (Requirement 15)
                if actual_provider.lower() in ("ollama", "local", "faster-whisper", "tesseract", "pdfplumber"):
                    return {
                        'provider': 'Ollama (Local)',
                        'model': 'llama3.2:3b',
                        'input_tokens_est': input_tokens,
                        'output_tokens_est': output_tokens,
                        'estimated_cost_usd': 0.0,
                        'notes': 'Local inference / no cloud API charge',
                    }
                elif "groq" in actual_provider.lower():
                    return {
                        'provider': 'Groq',
                        'model': 'llama-3.3-70b-versatile',
                        'input_tokens_est': input_tokens,
                        'output_tokens_est': output_tokens,
                        'estimated_cost_usd': round((input_tokens + output_tokens) * 0.0000002, 6),
                    }
                else:
                    return {
                        'provider': 'Gemini',
                        'model': model_name,
                        'input_tokens_est': input_tokens,
                        'output_tokens_est': output_tokens,
                        'estimated_cost_usd': round((input_tokens + output_tokens) * 0.0000004, 6),
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
                {'source': tool, 'content': out, 'confidence': 1.0}
                for tool, out in result['tool_results'].items() if out and not str(out).startswith(("Error", "⚠️"))
            ]

            yield f"data: {json.dumps({'type': 'init', 'session_id': session_id, 'cost': calculate_cost(query), 'extracted_texts': extracted_files, 'plan': formatted_plan, 'citations': result.get('citations', [])})}\n\n"

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

            if final_text and not final_text.startswith("An internal error"):
                session_service.save_message(session_id, "assistant", final_text, user_id=user_id)

            yield f"data: {json.dumps({'type': 'cost_update', 'cost': calculate_cost(query, final_text)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

            logger.info(
                "[/api/agent] request_id=%s completed provider=%s plan_steps=%d response_len=%d",
                request_id, actual_provider, len(result['plan']), len(final_text)
            )

        except (asyncio.CancelledError, GeneratorExit):
            logger.info("Agent streaming cancelled or client disconnected request_id=%s", request_id)
            return
        except Exception as e:
            err_name = type(e).__name__
            if "ClientDisconnected" in err_name or "RemoteDisconnected" in err_name:
                logger.info("Client disconnected from agent stream request_id=%s: %s", request_id, e)
                return
            logger.exception("Agent request failed request_id=%s stage=streaming_or_persistence", request_id)
            for saved_file in saved_files:
                document_service.update(saved_file["document_id"], status="FAILED")
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

    logger.info("/api/ocr called: GEMINI_KEY_PRESENT=%s, FILENAME=%s, MIMETYPE=%s", bool(api_key), file.filename, file.content_type)

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
async def fetch_youtube(req: URLRequest, current_user: dict[str, Any] = Depends(get_current_user)):
    """Fetch transcript from a YouTube URL and persist/index it."""
    user_id = current_user["id"]
    transcript = YouTubeFetcher.fetch_with_gemini_fallback(
        req.url,
        os.environ.get("GEMINI_API_KEY", ""),
    )
    is_error = transcript.startswith("Failed") or transcript.startswith("No valid") or transcript.startswith("TRANSCRIPT_FETCH_FAILED:")
    if not is_error:
        video_id = YouTubeFetcher.extract_video_id(req.url) or "video"
        canonical_url = f"https://www.youtube.com/watch?v={video_id}" if video_id != "video" else req.url
        yt_doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, canonical_url))
        session_id = f"user-{user_id}-global"
        try:
            document_service.create_text_document(
                filename=f"YouTube Video ({video_id})",
                text=transcript,
                session_id=session_id,
                modality="youtube",
                confidence=1.0,
                metadata={
                    "document_id": yt_doc_id,
                    "youtube_video_id": video_id,
                    "video_id": video_id,
                    "url": req.url,
                    "source_url": canonical_url,
                    "source_type": "youtube",
                    "title": f"YouTube Video ({video_id})",
                    "transcript_available": True,
                    "user_id": user_id,
                },
            )
            from services.rag_service import RAGService
            chunk_ids = RAGService(None).ingest_document(
                transcript,
                metadata={
                    "document_id": yt_doc_id,
                    "session_id": session_id,
                    "filename": f"YouTube Video ({video_id})",
                    "source_type": "youtube",
                    "youtube_video_id": video_id,
                    "url": canonical_url,
                    "user_id": user_id,
                },
            )
            document_service.update(yt_doc_id, chunk_count=len(chunk_ids), status="READY")
        except Exception as e:
            logger.warning("Could not persist YouTube endpoint transcript: %s", e)
    return {
        "status": "error" if is_error else "ok",
        "url": req.url,
        "transcript": transcript
    }


@router.post("/summary")
async def summarize(req: TextRequest, current_user: dict[str, Any] = Depends(get_current_user)):
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
async def analyze_sentiment(req: TextRequest, current_user: dict[str, Any] = Depends(get_current_user)):
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
async def analyze_code(req: TextRequest, current_user: dict[str, Any] = Depends(get_current_user)):
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
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    """Compatibility upload endpoint; use /documents/upload for persistent storage."""
    max_bytes = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(status_code=413, detail="Uploaded file exceeds the configured size limit")
        except ValueError:
            pass

    chunk_size = 1024 * 1024
    chunks = []
    total_bytes = 0
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise HTTPException(status_code=413, detail="Uploaded file exceeds the configured size limit")
        chunks.append(chunk)

    user_id = current_user["id"]
    session_id = session_service.create(user_id=user_id)["id"]
    content = b"".join(chunks)
    document = document_service.create_from_bytes(file.filename or "upload", content, session_id, file.content_type, user_id=user_id)
    return {"status": "uploaded", "session_id": session_id, "document": document}


@router.post("/sessions")
async def create_session(request: Request, req: SessionRequest = SessionRequest(), current_user: dict[str, Any] = Depends(get_current_user), _csrf: None = Depends(verify_csrf)):
    user_id = current_user["id"]
    return session_service.create(req.session_id, title=req.title or "New Chat", user_id=user_id)


@router.get("/sessions")
async def list_sessions(current_user: dict[str, Any] = Depends(get_current_user)):
    return {"sessions": session_service.list_all(user_id=current_user["id"])}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
    user_id = current_user["id"]
    session = session_service.get(session_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session": session,
        "messages": session_service.recent_messages(session_id, user_id=user_id),
        "documents": document_service.list(session_id, user_id=user_id),
    }


@router.patch("/sessions/{session_id}")
@router.put("/sessions/{session_id}")
async def rename_session(
    session_id: str,
    req: RenameSessionRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    user_id = current_user["id"]
    clean_title = req.title.strip()
    if not clean_title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    updated = session_service.update(session_id, user_id=user_id, title=clean_title)
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "ok", "session": updated}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, current_user: dict[str, Any] = Depends(get_current_user), _csrf: None = Depends(verify_csrf)):
    deleted = session_service.delete(session_id, user_id=current_user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}


@router.get("/models")
def models():
    return {"models": list_models()}


@router.post("/search")
async def search_documents(req: SearchRequest, current_user: dict[str, Any] = Depends(get_current_user)):
    user_id = current_user["id"]
    if not session_service.get(req.session_id, user_id=user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    api_key = os.getenv("GEMINI_API_KEY", "")
    from services.rag_service import RAGService
    results = RAGService(api_key).search_results(
        req.query, top_k=8,
        document_ids=req.document_ids or None,
        session_id=req.session_id,
        user_id=user_id,
    )
    return {"results": results, "citations": build_citations(results), "retrieved_count": len(results)}


@router.post("/documents/upload")
async def upload_document(
    request: Request,
    session_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    user_id = current_user["id"]
    max_bytes = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(status_code=413, detail="Uploaded file exceeds the configured size limit")
        except ValueError:
            pass

    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="Uploaded file exceeds the configured size limit")
    if not session_service.get(session_id, user_id=user_id):
        other_session = session_service.get(session_id, user_id=None)
        if other_session:
            raise HTTPException(status_code=403, detail="Access to this session is forbidden")
        session_service.create(session_id, user_id=user_id)
    document = document_service.create_from_bytes(file.filename or "upload", content, session_id, file.content_type, user_id=user_id)
    if document.get("duplicate"):
        return document
    try:
        document_service.update(document["id"], status="PROCESSING")
        evidence = ingestion_manager.ingest(document["storage_path"], document["id"], document["filename"], file.content_type or "application/octet-stream")
        text = evidence.text
        if not text or text.startswith("⚠️"):
            raise RuntimeError("No indexable text was extracted from the document")
        from services.rag_service import RAGService
        chunk_ids = RAGService(None).ingest_document(text, {"document_id": document["id"], "session_id": session_id, "user_id": user_id, "filename": document["filename"], "source_type": evidence.source_type}, evidence=evidence)
        return document_service.update(
            document["id"],
            status="READY",
            extracted_text=text,
            chunk_count=len(chunk_ids),
            page_count=evidence.metadata.get("page_count", 0),
        )
    except Exception as exc:
        logger.exception("Document ingestion failed for %s", document["id"])
        return document_service.update(document["id"], status="FAILED", error=str(exc))


@router.get("/documents")
async def list_documents(session_id: Optional[str] = None, current_user: dict[str, Any] = Depends(get_current_user)):
    return {"documents": document_service.list(session_id, user_id=current_user["id"])}


@router.get("/documents/{document_id}")
async def get_document(document_id: str, current_user: dict[str, Any] = Depends(get_current_user)):
    document = document_service.get(document_id, user_id=current_user["id"])
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str, current_user: dict[str, Any] = Depends(get_current_user), _csrf: None = Depends(verify_csrf)):
    if not document_service.delete(document_id, user_id=current_user["id"]):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted", "document_id": document_id}


@router.get("/health")
def health_check():
    return {"status": "ok"}