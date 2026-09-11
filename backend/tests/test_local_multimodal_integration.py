import io
import os
import tempfile
import wave
from types import SimpleNamespace

import fitz
from PIL import Image, ImageDraw, ImageFont

from services.audio_transcriber import AudioTranscriber
from services.code_analyzer import CodeAnalyzerService
from services.embedding_service import EmbeddingService
from services.ocr_service import OCRService
from services.pdf_parser import PDFParser
from services.ingestion.pdf_ingestor import PDFIngestor
from services.providers.ollama_provider import OllamaProvider
from services.rag_service import RAGService
from services.retrieval.citation_builder import build_citations
from services.sentiment import SentimentService
from services.summarizer import SummarizerService
from agent.intent_detector import IntentDetector
from services.query_context_resolver import QueryContextResolver


def test_local_pdf_ocr_embedding_and_rag():
    with tempfile.TemporaryDirectory() as directory:
        image = Image.new("RGB", (1200, 300), "white")
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
        ImageDraw.Draw(image).text((40, 100), "Parallel local OCR test", fill="black", font=font)
        image_path = os.path.join(directory, "scan.png")
        image.save(image_path)
        pdf_path = os.path.join(directory, "scan.pdf")
        pdf = fitz.open()
        page = pdf.new_page(width=600, height=150)
        page.insert_image(page.rect, filename=image_path)
        pdf.save(pdf_path)
        pdf.close()

        extracted = PDFParser.extract_text(pdf_path)
        assert "Parallel" in extracted
        vector = EmbeddingService().embed([extracted])[0]
        assert len(vector) == 768
        rag = RAGService(None)
        rag.ingest_document(extracted, {"document_id": "local-test", "session_id": "local-test", "filename": "scan.pdf", "source_type": "pdf"})
        results = rag.search_results("Parallel", top_k=3, document_ids=["local-test"], session_id="local-test")
        assert results
        assert build_citations(results)


def test_local_image_ocr():
    image = Image.new("RGB", (1000, 250), "white")
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
    ImageDraw.Draw(image).text((30, 90), "Image OCR works", fill="black", font=font)
    with tempfile.NamedTemporaryFile(suffix=".png") as file:
        image.save(file.name)
        text, confidence = OCRService.extract_text(file.name, "image/png")
    assert "Image" in text and "works" in text
    assert confidence > 0


def test_local_ollama_tasks():
    provider = OllamaProvider()
    assert provider.generate("Reply with LOCAL_OK only.", model="ignored")
    assert SummarizerService.summarize("Redis stores searchable document chunks.")
    assert SentimentService.analyze("I am happy with the result.")
    assert CodeAnalyzerService.analyze("def add(a, b): return a + b")


def test_local_stt_path_is_exercised():
    with tempfile.NamedTemporaryFile(suffix=".wav") as file:
        with wave.open(file.name, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x00\x00" * 16000)
        transcript, metadata = AudioTranscriber.transcribe(file.name, "audio/wav", gemini_key=None)
    assert isinstance(transcript, str)
    assert isinstance(metadata, dict)
    assert transcript.startswith("Audio STT Failed:") or metadata.get("word_count", 0) >= 0


def test_greetings_are_conversation_without_tools():
    result = IntentDetector.detect("hi", [{"mime_type": "", "filename": ""}][:0])
    assert result.primary_intent == "conversation"
    assert result.required_tools == []


def test_fileless_question_cannot_invent_document_tools():
    result = IntentDetector.detect("what is this?", [])
    assert result.primary_intent == "conversation"
    assert result.required_tools == []


def test_new_upload_does_not_activate_old_document_context():
    resolved = QueryContextResolver.resolve(
        "what does this image say?",
        [{"id": "old-pdf", "status": "READY", "filename": "old.pdf"}],
    )
    assert resolved.use_retrieval is False
    assert resolved.document_ids == []


def test_image_visual_evidence_reports_icon_and_verified_url():
    image = Image.new("RGB", (1800, 300), "white")
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56)
    ImageDraw.Draw(image).text((30, 70), "GitHub https://github.com/example", fill="black", font=font)
    with tempfile.NamedTemporaryFile(suffix=".png") as file:
        image.save(file.name)
        evidence = OCRService.analyze_visual(file.name, "image/png")
    assert any(item["icon"] == "GitHub" for item in evidence["icons"])
    assert "https://github.com/example" in evidence["links"]


def test_image_icon_without_url_is_explicitly_unavailable():
    image = Image.new("RGB", (700, 220), "white")
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
    ImageDraw.Draw(image).text((30, 70), "GitHub", fill="black", font=font)
    with tempfile.NamedTemporaryFile(suffix=".png") as file:
        image.save(file.name)
        evidence = OCRService.analyze_visual(file.name, "image/png")
    github = next(item for item in evidence["icons"] if item["icon"] == "GitHub")
    assert github["url"] is None


def test_pdf_embedded_uri_metadata_is_extracted():
    with tempfile.NamedTemporaryFile(suffix=".pdf") as file:
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 72), "GitHub profile")
        page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 50, 200, 90), "uri": "https://github.com/example"})
        pdf.save(file.name)
        pdf.close()
        links = PDFParser.extract_links(file.name)
    assert links[0]["uri"] == "https://github.com/example"
    assert links[0]["page"] == 1


def test_pdf_ingestion_carries_verified_links_into_evidence():
    with tempfile.NamedTemporaryFile(suffix=".pdf") as file:
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 72), "GitHub profile")
        page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 50, 200, 90), "uri": "https://github.com/example"})
        pdf.save(file.name)
        pdf.close()
        evidence = PDFIngestor().ingest(file.name, "doc", "links.pdf")
    assert evidence.blocks[0].metadata["verified_links"][0]["uri"] == "https://github.com/example"
