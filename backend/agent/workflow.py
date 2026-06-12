import logging
import asyncio
import os
import re
from services.gemini_service import GeminiService, GeminiServiceError
from services.groq_service import GroqService, GroqServiceError
from agent.intent_detector import IntentDetector
from agent.planner import Planner
from services.pdf_parser import PDFParser
from services.ocr_service import OCRService
from services.audio_transcriber import AudioTranscriber
from services.youtube_fetcher import YouTubeFetcher
from services.rag_service import RAGService

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Helper: Groq-first, Gemini-fallback text generation.
# Used for ALL text-in / text-out steps inside the workflow.
# Gemini is never called here for file/multimodal work — that
# stays in the individual tool branches (pdf_parser, ocr, stt).
# ─────────────────────────────────────────────────────────────
def _generate_text(
    prompt: str,
    gemini_api_key: str,
    model_name: str = "gemini-2.5-flash",
    system_prompt: str = None,
) -> str:
    """
    Try Groq first.  If Groq fails → try Gemini.
    If Gemini also fails → retry Groq one last time.
    Always returns a string; never raises.
    """
    groq_key = os.environ.get("GROQ_API_KEY", "")

    # Attempt 1: Groq
    if groq_key:
        try:
            text = GroqService.generate_text(
                prompt=prompt,
                api_key=groq_key,
                system_prompt=system_prompt,
            )
            logger.info("[LLM] Groq responded successfully.")
            return text
        except GroqServiceError as groq_err:
            logger.warning(
                "[LLM] Groq failed (%s): %s — falling back to Gemini.",
                groq_err.code, groq_err,
            )
    else:
        logger.info("[LLM] GROQ_API_KEY not set — using Gemini directly.")

    # Attempt 2: Gemini
    if gemini_api_key:
        try:
            full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            res = GeminiService.generate_content(
                full_prompt,
                api_key=gemini_api_key,
                model_name=model_name,
            )
            text = res.text.strip() if getattr(res, "text", None) else ""
            logger.info("[LLM] Gemini responded successfully (fallback).")
            return text
        except GeminiServiceError as gem_err:
            logger.warning(
                "[LLM] Gemini also failed (%s): %s — retrying Groq.",
                gem_err.code, gem_err,
            )

    # Attempt 3: Groq retry
    if groq_key:
        try:
            text = GroqService.generate_text(
                prompt=prompt,
                api_key=groq_key,
                system_prompt=system_prompt,
            )
            logger.info("[LLM] Groq responded on second attempt.")
            return text
        except GroqServiceError as groq_err2:
            logger.error("[LLM] Groq second attempt failed: %s", groq_err2)

    return (
        "All AI providers are currently unavailable (Groq + Gemini both failed). "
        "Please check your API keys or try again in a moment."
    )


class AgentWorkflow:
    """Manages the full execution lifecycle of a query."""

    @staticmethod
    async def execute(
        query: str,
        files: list[dict],
        api_key: str,
        model_name: str = "gemini-2.5-flash",
    ):
        # 1. Intent Detection
        intent = IntentDetector.detect(query, files, api_key, model_name)

        if intent.is_ambiguous and intent.follow_up_question:
            return {
                "intent": intent.model_dump() if hasattr(intent, "model_dump") else intent.dict(),
                "plan": [],
                "tool_results": {},
                "final_response": intent.follow_up_question,
                "audio_url": None,
            }

        # 2. Planning
        plan = Planner.create_plan(intent.required_tools)

        # 3. Parallel Tool Execution
        # pdf_parser / ocr / audio_stt stay on Gemini — multimodal only.
        results = {}
        rag_service = RAGService(api_key) if api_key else None

        async def run_tool(step):
            tool = step["tool"]
            logger.info(f"Executing tool: {tool}")
            output = ""

            try:
                if tool == "pdf_parser":
                    # Gemini only — multimodal PDF extraction
                    pdf_file = next((f for f in files if f["mime_type"] == "application/pdf"), None)
                    if pdf_file:
                        output = PDFParser.extract_text(
                            pdf_file["path"], api_key=api_key, model_name=model_name
                        )
                        if rag_service and output:
                            try:
                                rag_service.ingest_document(output)
                            except Exception as e:
                                logger.exception(f"RAG ingestion failed: {e}")

                elif tool == "ocr":
                    # Gemini only — vision OCR
                    img_file = next((f for f in files if f["mime_type"].startswith("image/")), None)
                    if img_file:
                        logger.info(
                            "Workflow invoking OCRService.extract_text: GEMINI_KEY_PRESENT=%s, KEY_PREFIX=%s, FILE=%s, MIMETYPE=%s",
                            bool(api_key),
                            (api_key[:10] + "...") if api_key else "N/A",
                            img_file["path"],
                            img_file["mime_type"],
                        )
                        output, _ = OCRService.extract_text(
                            img_file["path"], img_file["mime_type"],
                            gemini_key=api_key, model_name=model_name,
                        )

                elif tool == "audio_stt":
                    # Gemini only — audio/video transcription
                    audio_file = next(
                        (f for f in files if f["mime_type"].startswith("audio/") or f["mime_type"].startswith("video/")),
                        None
                    )
                    if audio_file:
                        logger.info(
                            "Workflow audio_stt selected file: %s (%s)",
                            audio_file["filename"],
                            audio_file["mime_type"],
                        )
                        output, audio_meta = AudioTranscriber.transcribe(
                            audio_file["path"], audio_file["mime_type"],
                            gemini_key=api_key, model_name=model_name,
                        )
                        if audio_meta:
                            results["_audio_meta"] = audio_meta
                    else:
                        output = "Audio STT Failed: no audio or video file found to transcribe."

                elif tool == "youtube_fetcher":
                    try:
                        output = YouTubeFetcher.fetch_transcript(query)
                    except Exception as e:
                        logger.exception(f"YouTube transcript tool failed: {e}")
                        output = f"TRANSCRIPT_FETCH_FAILED: {type(e).__name__}: {str(e)}"
                    if output.startswith("TRANSCRIPT_FETCH_FAILED:"):
                        logger.warning(f"YouTube tool failure: {output}")
                    elif output and len(output) > 100:
                        logger.info(f"YouTube transcript fetched ({len(output)} chars)")
                    else:
                        logger.warning(f"YouTube transcript too short: {len(output) if output else 0} chars")

                elif tool == "rag_search":
                    if rag_service:
                        output = rag_service.search(query)

            except Exception as e:
                output = f"Error executing {tool}: {str(e)}"

            return tool, output

        tasks = [run_tool(step) for step in plan]
        completed = await asyncio.gather(*tasks)

        for tool, output in completed:
            results[tool] = output

        # ── Raw extract shortcut ─────────────────────────────
        extract_commands = [
            "/extracttext", "extract", "extract text",
            "pdf text", "show extracted text", "extract pdf", "raw pdf",
        ]
        if query.strip().lower() in extract_commands:
            pdf_text = results.get("pdf_parser", "")
            return {
                "intent": intent.model_dump() if hasattr(intent, "model_dump") else intent.dict(),
                "plan": plan,
                "tool_results": results,
                "final_response": pdf_text if pdf_text else "No text extracted from PDF.",
                "audio_url": None,
            }

        # ── TEST CASE 4: YouTube URL found inside PDF text ───
        pdf_text = results.get("pdf_parser", "")
        if pdf_text and not pdf_text.startswith("⚠️"):
            youtube_url_pattern = (
                r"(https?://(?:www\.)?(?:youtube\.com/watch\?v=[\w-]+(?:[^\s]*)?|youtu\.be/[\w-]+))"
            )
            youtube_match = re.search(youtube_url_pattern, pdf_text)

            if youtube_match:
                youtube_url = youtube_match.group(1)
                logger.info(f"YouTube URL detected in PDF: {youtube_url}")

                try:
                    transcript = YouTubeFetcher.fetch_transcript(youtube_url)
                    if (
                        transcript
                        and not transcript.startswith("TRANSCRIPT_FETCH_FAILED:")
                        and len(transcript) > 100
                    ):
                        summary_prompt = (
                            f"Summarize this video transcript in exactly ONE sentence "
                            f"(maximum 25 words):\n\n{transcript}"
                        )
                        # Groq-first text generation
                        one_line_summary = _generate_text(
                            prompt=summary_prompt,
                            gemini_api_key=api_key,
                            model_name=model_name,
                        )
                        if one_line_summary and not one_line_summary.startswith("All AI providers"):
                            logger.info(f"YouTube summary: {one_line_summary[:100]}")
                            results["youtube_fetcher"] = one_line_summary
                        else:
                            results["youtube_fetcher"] = "⚠️ Could not summarize video transcript."
                    else:
                        results["youtube_fetcher"] = "⚠️ Could not retrieve video transcript."
                except Exception as e:
                    logger.exception(f"YouTube fetch failed: {e}")
                    results["youtube_fetcher"] = "⚠️ Could not retrieve video transcript."

        # 4. Final Response Generation
        if api_key or os.environ.get("GROQ_API_KEY"):

            # Return YouTube summary directly
            youtube_summary = results.get("youtube_fetcher", "")
            if youtube_summary and not youtube_summary.startswith("⚠️"):
                return {
                    "intent": intent.model_dump() if hasattr(intent, "model_dump") else intent.dict(),
                    "plan": plan,
                    "tool_results": results,
                    "final_response": youtube_summary,
                    "audio_url": None,
                }
            if youtube_summary and youtube_summary.startswith("⚠️"):
                return {
                    "intent": intent.model_dump() if hasattr(intent, "model_dump") else intent.dict(),
                    "plan": plan,
                    "tool_results": results,
                    "final_response": youtube_summary,
                    "audio_url": None,
                }

            # Build context from successful tool outputs
            context_parts = []
            for t, o in results.items():
                if t.startswith("_") or t == "youtube_fetcher":
                    continue
                is_error = not o or (
                    isinstance(o, str)
                    and (
                        o.startswith("Error")
                        or o.startswith("OCR Failed")
                        or o.startswith("Audio STT Failed")
                        or o.startswith("TRANSCRIPT_FETCH_FAILED:")
                        or o.startswith("⚠️")
                    )
                )
                if not is_error:
                    context_parts.append(f"[{t.upper()} OUTPUT]\n{o}")
                elif o:
                    logger.warning(f"Tool {t} error: {str(o)[:100]}")

            context = "\n\n".join(context_parts)

            failed_tools = [
                t for t, o in results.items()
                if not t.startswith("_")
                and (
                    not o
                    or (
                        isinstance(o, str)
                        and (
                            o.startswith("Error")
                            or o.startswith("OCR Failed")
                            or o.startswith("Audio STT Failed")
                            or o.startswith("TRANSCRIPT_FETCH_FAILED:")
                            or o.startswith("⚠️")
                        )
                    )
                )
            ]
            successful_tools = [
                t for t in results if not t.startswith("_") and t not in failed_tools
            ]

            if not context.strip() and files and not successful_tools:
                return {
                    "intent": intent.model_dump() if hasattr(intent, "model_dump") else intent.dict(),
                    "plan": plan,
                    "tool_results": results,
                    "final_response": (
                        f"⚠️ Could not extract content from your file(s). "
                        f"Failed tools: {', '.join(failed_tools)}. "
                        f"If using a scanned PDF, ensure Tesseract is installed. "
                        f"If the Gemini quota is exceeded, wait 60 seconds and retry."
                    ),
                    "audio_url": None,
                }

            # ── TEST CASE 5: Cross-input similarity comparison ─
            audio_output = results.get("audio_stt", "")
            pdf_output_for_compare = results.get("pdf_parser", "")
            compare_keywords = [
                "same topic", "compare", "similar",
                "discuss the same", "both discuss", "match",
            ]
            is_comparison_query = any(kw in query.lower() for kw in compare_keywords)

            if (
                is_comparison_query
                and audio_output
                and isinstance(audio_output, str)
                and not audio_output.startswith("Audio STT Failed")
                and pdf_output_for_compare
                and isinstance(pdf_output_for_compare, str)
                and not pdf_output_for_compare.startswith("⚠️")
            ):
                comparison_prompt = (
                    f"DOCUMENT 1 (Audio Transcript):\n{audio_output}\n\n"
                    f"DOCUMENT 2 (PDF Content):\n{pdf_output_for_compare}\n\n"
                    f"User Query: {query}\n\n"
                    "Provide:\n"
                    "1. Whether they discuss the same topic (Yes / No)\n"
                    "2. Similarity score (0–100%)\n"
                    "3. Common themes\n"
                    "4. Key differences"
                )
                final_response = _generate_text(
                    prompt=comparison_prompt,
                    gemini_api_key=api_key,
                    model_name=model_name,
                    system_prompt=(
                        "You are an expert analyst. Compare the two documents and "
                        "determine if they discuss the same topic."
                    ),
                )

            else:
                # Normal routing — pick the right system prompt
                sys_instructions = (
                    "You are a powerful AI assistant. Answer the user's query "
                    "based STRICTLY on the provided tool outputs."
                )

                if "summarizer" in intent.required_tools:
                    from services.summarizer import SummarizerService
                    sys_instructions = SummarizerService.get_system_prompt()

                elif "sentiment" in intent.required_tools:
                    from services.sentiment import SentimentService
                    sys_instructions = SentimentService.get_system_prompt()

                elif "code_analyzer" in intent.required_tools:
                    ocr_output = results.get("ocr", "")
                    if (
                        ocr_output
                        and isinstance(ocr_output, str)
                        and not ocr_output.startswith("OCR Failed")
                        and len(ocr_output) > 20
                    ):
                        from services.code_analyzer import CodeAnalyzerService
                        sys_instructions = CodeAnalyzerService.get_system_prompt()
                    else:
                        sys_instructions = (
                            "You are a powerful AI assistant. The image did not appear to "
                            "contain readable code. Answer based on available context."
                        )

                # TC1: Inject audio duration into context
                audio_meta = results.get("_audio_meta", {})
                if audio_meta and audio_meta.get("duration_seconds"):
                    duration_sec = audio_meta["duration_seconds"]
                    duration_min = round(duration_sec / 60, 1)
                    context += (
                        f"\n\n[AUDIO METADATA]\n"
                        f"Estimated Duration: {duration_min} minutes ({duration_sec} seconds)\n"
                        f"Word Count: {audio_meta.get('word_count', 'N/A')}"
                    )

                user_prompt = (
                    f"User Query: {query}\n\n"
                    f"Context from tools:\n{context}\n\n"
                    "Provide the final output."
                )

                # Groq-first text generation for all final responses
                final_response = _generate_text(
                    prompt=user_prompt,
                    gemini_api_key=api_key,
                    model_name=model_name,
                    system_prompt=sys_instructions,
                )

        else:
            final_response = "LLM Provider Not Configured. Please add GEMINI_API_KEY or GROQ_API_KEY."

        return {
            "intent": intent.model_dump() if hasattr(intent, "model_dump") else intent.dict(),
            "plan": plan,
            "tool_results": results,
            "final_response": final_response,
            "audio_url": None,
        }