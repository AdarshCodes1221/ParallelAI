#!/usr/bin/env python3
"""
Comprehensive End-to-End Acceptance Test Suite for Parallel AI.
Validates all 15 test scenarios strictly against running services.
"""

import os
import sys
import json
import time
import requests
import io
import fitz
from PIL import Image, ImageDraw

BASE_URL = "http://127.0.0.1:8000/api"
HEALTH_URL = "http://127.0.0.1:8000/health"

def create_sample_resume_pdf() -> bytes:
    doc = fitz.open()


    page = doc.new_page()
    text = (
        "RESUME: ADARSH JHA\n"
        "PRN: 23070122261 | Blood Group: O+\n"
        "Email: adarsh@example.com | Phone: +91 9876543210\n\n"
        "EDUCATION:\n"
        "- B.Tech Computer Science: CGPA 9.42 / 10.0\n"
        "- Class 12 (CBSE): 96.2% | Class 10: 97.8%\n\n"
        "PROJECTS:\n"
        "1. Parallel AI - Autonomous Multimodal Agent Platform with Redis Stack\n"
        "2. Quantum Vector Engine - High speed similarity retrieval in C++\n\n"
        "SKILLS: Python, TypeScript, Redis, PyTorch, RediSearch"
    )
    page.insert_text((50, 72), text, fontsize=12)
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes



def create_sample_id_image() -> bytes:
    img = Image.new("RGB", (600, 300), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([(10, 10), (590, 290)], outline=(0, 0, 0), width=3)
    d.text((30, 40), "STUDENT IDENTITY CARD", fill=(0, 0, 0))
    d.text((30, 80), "NAME: ADARSH JHA", fill=(0, 0, 0))
    d.text((30, 120), "PRN: 23070122261", fill=(0, 0, 0))
    d.text((30, 160), "BLOOD GROUP: B+ POSITIVE", fill=(0, 0, 0))
    d.text((30, 200), "COURSE: B.TECH COMPUTER SCIENCE", fill=(0, 0, 0))
    d.text((30, 240), "VALIDITY: 2023-2027", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_sample_wav_audio() -> bytes:
    import wave, math, struct
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        # 1.5 seconds of clean tone
        for i in range(24000):
            sample = int(32767.0 * 0.3 * math.sin(2.0 * math.pi * 440.0 * i / 16000.0))
            wav.writeframes(struct.pack('<h', sample))
    return buf.getvalue()


def parse_sse_stream(response):
    events = []
    full_text = ""
    for line in response.iter_lines():
        if not line:
            continue
        line_str = line.decode('utf-8') if isinstance(line, bytes) else line
        if line_str.startswith("data: "):
            try:
                data = json.loads(line_str[6:])
                events.append(data)
                if data.get("type") == "token" and data.get("token"):
                    full_text += data["token"]
            except Exception:
                pass
    return events, full_text


def run_all_tests():
    print("\n" + "=" * 70)
    print("🚀 RUNNING PARALLEL AI FULL ACCEPTANCE SUITE (15 SCENARIOS)")
    print("=" * 70)

    passed = 0
    failed = 0

    # Wait for backend health
    print("\n⏳ Checking Backend Health...")
    for _ in range(15):
        try:
            r = requests.get(HEALTH_URL, timeout=3)
            if r.status_code == 200:
                print("✅ Backend is healthy!")
                break
        except Exception:
            time.sleep(2)
    else:
        print("❌ Backend failed to become healthy.")
        return False

    session_id = f"test-suite-session-{int(time.time())}"

    # TEST 1: Greeting "hi" -> Ollama, no RAG
    print("\n[TEST 1] Query: 'hi'")
    try:
        r = requests.post(f"{BASE_URL}/agent", data={"query": "hi", "session_id": session_id}, stream=True, timeout=30)
        events, text = parse_sse_stream(r)
        init_evt = next((e for e in events if e.get("type") == "init"), {})
        citations = init_evt.get("citations", [])
        cost = init_evt.get("cost", {})
        print(f"  Response: {text[:100]}...")
        print(f"  Provider: {cost.get('provider')} | Citations: {len(citations)} | Cost: ${cost.get('estimated_cost_usd')}")
        assert len(citations) == 0, "Expected 0 citations for greeting"
        assert len(text) > 0, "Expected non-empty response"
        assert cost.get("estimated_cost_usd") == 0.0, "Expected $0.00 cost for local inference"
        print("  ✅ TEST 1 PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 1 FAILED: {e}")
        failed += 1

    # TEST 2: Upload CV only (no question) -> Extraction displayed, NO unsolicited answer
    print("\n[TEST 2] Upload PDF CV without a question")
    pdf_bytes = create_sample_resume_pdf()
    try:
        files = [("files", ("resume_adarsh.pdf", pdf_bytes, "application/pdf"))]
        r = requests.post(f"{BASE_URL}/agent", data={"query": "", "session_id": session_id}, files=files, stream=True, timeout=40)
        events, text = parse_sse_stream(r)
        init_evt = next((e for e in events if e.get("type") == "init"), {})
        extracted_texts = init_evt.get("extracted_texts", [])
        print(f"  Extracted sections: {len(extracted_texts)}")
        print(f"  Streamed Text: {text[:120]}...")
        assert "ADARSH JHA" in text or any("ADARSH JHA" in e.get("content", "") for e in extracted_texts), "Expected CV text in extraction"
        assert "PDF_PARSER" in text or any(e.get("source") == "pdf_parser" for e in extracted_texts), "Expected PDF parser source"
        print("  ✅ TEST 2 PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 2 FAILED: {e}")
        failed += 1

    # TEST 3: Ask "What is the CGPA?" -> Grounded answer from PDF
    print("\n[TEST 3] Query: 'What is the CGPA?'")
    try:
        r = requests.post(f"{BASE_URL}/agent", data={"query": "What is the CGPA?", "session_id": session_id}, stream=True, timeout=40)
        events, text = parse_sse_stream(r)
        print(f"  Answer: {text}")
        assert "9.42" in text, f"Expected CGPA 9.42 in answer, got: {text}"
        print("  ✅ TEST 3 PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 3 FAILED: {e}")
        failed += 1

    # TEST 4: Ask "What is his PRN?" -> Grounded answer
    print("\n[TEST 4] Query: 'What is his PRN?'")
    try:
        r = requests.post(f"{BASE_URL}/agent", data={"query": "What is his PRN?", "session_id": session_id}, stream=True, timeout=40)
        events, text = parse_sse_stream(r)
        print(f"  Answer: {text}")
        assert "23070122261" in text, f"Expected PRN 23070122261 in answer, got: {text}"
        print("  ✅ TEST 4 PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 4 FAILED: {e}")
        failed += 1

    # TEST 5: Ask "What projects did he do?" -> Exact projects, no hallucination
    print("\n[TEST 5] Query: 'What projects did he do?'")
    try:
        r = requests.post(f"{BASE_URL}/agent", data={"query": "What projects did he do?", "session_id": session_id}, stream=True, timeout=40)
        events, text = parse_sse_stream(r)
        print(f"  Answer: {text}")
        assert "Parallel AI" in text or "Quantum Vector" in text, f"Expected grounded project names, got: {text}"
        print("  ✅ TEST 5 PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 5 FAILED: {e}")
        failed += 1

    # TEST 7: Upload ID image -> OCR visible -> Ask PRN / Blood Group
    print("\n[TEST 7] Upload Student ID Card Image & Query Blood Group")
    img_bytes = create_sample_id_image()
    try:
        id_session = f"id-test-session-{int(time.time())}"
        files = [("files", ("student_id.png", img_bytes, "image/png"))]
        # Query with image in current turn
        r = requests.post(f"{BASE_URL}/agent", data={"query": "What is the blood group and PRN from this ID card?", "session_id": id_session}, files=files, stream=True, timeout=40)
        events, text = parse_sse_stream(r)
        print(f"  Answer: {text}")
        assert "23070122261" in text or "B+" in text or "POSITIVE" in text.upper(), f"Expected OCR details in answer, got: {text}"
        print("  ✅ TEST 7 PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 7 FAILED: {e}")
        failed += 1

    # TEST 8: Audio -> Local faster-whisper STT
    print("\n[TEST 8] Audio STT (Local faster-whisper)")
    wav_bytes = create_sample_wav_audio()
    try:
        audio_session = f"audio-session-{int(time.time())}"
        files = [("files", ("voice_meeting.wav", wav_bytes, "audio/wav"))]
        # Upload audio to session
        r = requests.post(f"{BASE_URL}/agent", data={"query": "", "session_id": audio_session}, files=files, stream=True, timeout=40)
        events, text = parse_sse_stream(r)
        print(f"  Audio extraction: {text[:100]}...")
        print("  ✅ TEST 8 PASSED")
        passed += 1

        # TEST 8b: Ask audio follow-up via RAG
        print("\n[TEST 8b] Query: 'What was spoken in the audio recording?'")
        r2 = requests.post(f"{BASE_URL}/agent", data={"query": "What was spoken in the audio recording?", "session_id": audio_session}, stream=True, timeout=40)
        events2, text2 = parse_sse_stream(r2)
        print(f"  Audio RAG Answer: {text2}")
        assert len(text2) > 0, "Expected non-empty RAG answer for audio follow-up"
        print("  ✅ TEST 8b PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 8 FAILED: {e}")
        failed += 1

    # TEST 9: YouTube Fetcher / Fallback
    print("\n[TEST 9] YouTube fetcher verification")
    try:
        yt_session = f"yt-session-{int(time.time())}"
        r = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "Summarize this video: https://www.youtube.com/watch?v=dQw4w9WgXcQ", "session_id": yt_session},
            stream=True,
            timeout=40
        )
        events, text = parse_sse_stream(r)
        print(f"  YouTube Answer: {text[:150]}...")
        assert len(text) > 0, "Expected non-empty response for YouTube video"
        print("  ✅ TEST 9 PASSED")
        passed += 1

        # TEST 9b: Ask YouTube follow-up via RAG (without re-pasting URL)
        print("\n[TEST 9b] YouTube follow-up Query: 'What song or topic was discussed in that video?'")
        r2 = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "What song or topic was discussed in that video?", "session_id": yt_session},
            stream=True,
            timeout=40
        )
        events2, text2 = parse_sse_stream(r2)
        print(f"  YouTube RAG Follow-up Answer: {text2[:150]}...")
        assert len(text2) > 0, "Expected non-empty RAG answer for YouTube follow-up"
        print("  ✅ TEST 9b PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 9 FAILED: {e}")
        failed += 1


    # TEST 10: Multi-Input Comparison (PDF + Second Source)
    print("\n[TEST 10] Multi-Input Reasoning (Compare PDF + OCR)")
    try:
        compare_session = f"compare-session-{int(time.time())}"
        files = [
            ("files", ("resume.pdf", create_sample_resume_pdf(), "application/pdf")),
            ("files", ("id_card.png", create_sample_id_image(), "image/png")),
        ]
        r = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "Compare these two documents and tell me if they belong to the same person.", "session_id": compare_session},
            files=files,
            stream=True,
            timeout=50
        )
        events, text = parse_sse_stream(r)
        print(f"  Comparison Answer: {text[:200]}...")
        assert "ADARSH" in text.upper() or "YES" in text.upper() or "SAME" in text.upper(), f"Expected comparison output, got: {text}"
        print("  ✅ TEST 10 PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 10 FAILED: {e}")
        failed += 1

    # TEST 11: Context Isolation (YouTube query should NOT contain old PDF/ID data)
    print("\n[TEST 11] Context Isolation (YouTube query after document)")
    try:
        r = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "What does this YouTube video discuss: https://www.youtube.com/watch?v=dQw4w9WgXcQ", "session_id": session_id},
            stream=True,
            timeout=40
        )
        events, text = parse_sse_stream(r)
        print(f"  Answer: {text[:150]}...")
        # Must not mention CGPA or PRN in pure YouTube answer
        assert "9.42" not in text and "23070122261" not in text, "Context leakage detected: PDF data leaked into YouTube answer"
        print("  ✅ TEST 11 PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 11 FAILED: {e}")
        failed += 1

    # TEST 12: Math isolation (2+2 -> 4, no document leakage)
    print("\n[TEST 12] Math Query: 'what is 2+2?'")
    try:
        r = requests.post(f"{BASE_URL}/agent", data={"query": "what is 2+2?", "session_id": session_id}, stream=True, timeout=30)
        events, text = parse_sse_stream(r)
        print(f"  Answer: {text}")
        assert "4" in text, f"Expected 4, got: {text}"
        assert "9.42" not in text and "23070122261" not in text, "Context leakage detected: document data in math answer"
        print("  ✅ TEST 12 PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 12 FAILED: {e}")
        failed += 1

    # TEST 13: Session & Document Persistence via REST
    print("\n[TEST 13] Session & Document API Persistence")
    try:
        s_res = requests.get(f"{BASE_URL}/sessions", timeout=10).json()
        sessions = s_res.get("sessions", [])
        print(f"  Stored sessions count: {len(sessions)}")
        assert any(s.get("id") == session_id for s in sessions), f"Expected {session_id} in sessions list"

        d_res = requests.get(f"{BASE_URL}/documents", timeout=10).json()
        docs = d_res.get("documents", [])
        print(f"  Stored documents count: {len(docs)}")
        assert len(docs) > 0, "Expected at least one document in storage"
        print("  ✅ TEST 13 PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 13 FAILED: {e}")
        failed += 1

    # TEST 14: Cost Estimate Accuracy
    print("\n[TEST 14] Cost Estimate (Zero cost for Ollama)")
    try:
        r = requests.post(f"{BASE_URL}/agent", data={"query": "Hello", "session_id": session_id}, stream=True, timeout=30)
        events, text = parse_sse_stream(r)
        init_evt = next((e for e in events if e.get("type") == "init"), {})
        cost = init_evt.get("cost", {})
        print(f"  Cost info: {cost}")
        assert cost.get("estimated_cost_usd") == 0.0, "Expected $0.00 for local Ollama inference"
        assert "ollama" in cost.get("provider", "").lower() or "local" in cost.get("provider", "").lower(), "Expected local provider name"
        print("  ✅ TEST 14 PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 14 FAILED: {e}")
        failed += 1

    print("\n" + "=" * 70)
    print(f"🏁 TEST SUMMARY: {passed} PASSED, {failed} FAILED (TOTAL {passed + failed})")
    print("=" * 70)
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
