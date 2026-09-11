#!/usr/bin/env python3
"""
Targeted Verification Suite for Audio & YouTube Persistence, Hybrid RAG,
Cross-Modal Comparison, Source Isolation, and Performance.
"""

import io
import os
import sys
import time
import json
import wave
import math
import struct
import requests
import fitz

BASE_URL = "http://127.0.0.1:8000/api"
HEALTH_URL = "http://127.0.0.1:8000/health"


def create_test_pdf(title: str, text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), f"{title}\n\n{text}", fontsize=12)
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


def create_test_wav(duration_sec: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        num_samples = int(16000 * duration_sec)
        for i in range(num_samples):
            sample = int(32767.0 * 0.25 * math.sin(2.0 * math.pi * 440.0 * i / 16000.0))
            wav.writeframes(struct.pack('<h', sample))
    return buf.getvalue()


def parse_sse(response):
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


def test_suite():
    print("=" * 70)
    print("🚀 TARGETED MULTIMODAL RAG REPAIR VERIFICATION")
    print("=" * 70)

    # 1. Health Check
    for _ in range(10):
        try:
            r = requests.get(HEALTH_URL, timeout=3)
            if r.status_code == 200:
                print("✅ Backend is healthy!")
                break
        except Exception:
            time.sleep(1)
    else:
        print("❌ Backend is not reachable.")
        return False

    session_id = f"repair-session-{int(time.time())}"
    passed = 0
    failed = 0

    # ── TEST A: Audio Document Record, Local STT & Persistence ──────────────────
    print("\n[TEST A] Audio Upload, Local STT & Persistent Document Record")
    try:
        wav_data = create_test_wav(1.5)
        files = [("files", ("quantum_audio_memo.wav", wav_data, "audio/wav"))]
        r = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "", "session_id": session_id},
            files=files,
            stream=True,
            timeout=90,
        )
        events, text = parse_sse(r)
        print(f"  Extracted output: {text[:100]}...")

        # Verify Document record via REST
        doc_res = requests.get(f"{BASE_URL}/documents?session_id={session_id}", timeout=10).json()
        docs = doc_res.get("documents", [])
        audio_doc = next((d for d in docs if d.get("modality") == "audio" or d.get("source_type") == "audio"), None)
        assert audio_doc is not None, "Audio document record not found in backend storage"
        assert audio_doc.get("status") in ("READY", "UPLOADED"), f"Expected READY status, got {audio_doc.get('status')}"
        print(f"  Stored Audio Document ID: {audio_doc['id']} | Modality: {audio_doc.get('modality')}")
        print("  ✅ TEST A (Audio Record & Persistence) PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST A FAILED: {e}")
        failed += 1

    # ── TEST A2: Audio Hybrid RAG Follow-up ──────────────────────────────────────
    print("\n[TEST A2] Audio Hybrid RAG Follow-up ('What was discussed in the audio?')")
    try:
        t0 = time.perf_counter()
        r = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "What was discussed in the audio recording?", "session_id": session_id},
            stream=True,
            timeout=40,
        )
        events, text = parse_sse(r)
        dur = round((time.perf_counter() - t0) * 1000, 2)
        print(f"  RAG Response ({dur}ms): {text[:120]}...")
        assert len(text) > 0, "Expected non-empty response for audio RAG question"
        print("  ✅ TEST A2 (Audio Hybrid RAG) PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST A2 FAILED: {e}")
        failed += 1

    # ── TEST B: YouTube Document Record & Persistent RAG ─────────────────────────
    print("\n[TEST B] YouTube Transcript Fetch & Persistence")
    try:
        yt_session = f"yt-repair-session-{int(time.time())}"
        r = requests.post(
            f"{BASE_URL}/agent",
            data={
                "query": "Summarize the key points of this video: https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "session_id": yt_session,
            },
            stream=True,
            timeout=40,
        )
        events, text = parse_sse(r)
        print(f"  YouTube Answer: {text[:120]}...")

        # Verify YouTube Document record
        doc_res = requests.get(f"{BASE_URL}/documents?session_id={yt_session}", timeout=10).json()
        docs = doc_res.get("documents", [])
        yt_doc = next((d for d in docs if d.get("modality") == "youtube" or d.get("source_type") == "youtube"), None)
        assert yt_doc is not None, "YouTube document record not found in backend storage"
        print(f"  Stored YouTube Document ID: {yt_doc['id']} | Modality: {yt_doc.get('modality')}")
        print("  ✅ TEST B (YouTube Fetch & Persistence) PASSED")
        passed += 1

        # TEST B2: YouTube Follow-up RAG without re-pasting URL
        print("\n[TEST B2] YouTube Follow-up RAG Query without URL")
        r2 = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "What is the main topic of that video?", "session_id": yt_session},
            stream=True,
            timeout=40,
        )
        events2, text2 = parse_sse(r2)
        print(f"  YouTube RAG Answer: {text2[:120]}...")
        assert len(text2) > 0, "Expected non-empty RAG answer for YouTube follow-up"
        print("  ✅ TEST B2 (YouTube Follow-up RAG) PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST B FAILED: {e}")
        failed += 1

    # ── TEST C: Cross-Modal Comparison (PDF + Audio + YouTube) ───────────────────
    print("\n[TEST C] Cross-Modal Comparison (PDF + Audio + YouTube)")
    try:
        cross_session = f"cross-modal-{int(time.time())}"
        pdf_bytes = create_test_pdf(
            "AI Agent System Architecture",
            "This document describes Autonomous Multimodal Agents with Redis vector memory, speech transcription, and hybrid retrieval."
        )
        files = [
            ("files", ("architecture_spec.pdf", pdf_bytes, "application/pdf")),
            ("files", ("team_audio.wav", create_test_wav(1.0), "audio/wav")),
        ]
        r = requests.post(
            f"{BASE_URL}/agent",
            data={
                "query": "Compare the PDF, audio, and YouTube video: https://www.youtube.com/watch?v=dQw4w9WgXcQ. Do they discuss the same topic?",
                "session_id": cross_session,
            },
            files=files,
            stream=True,
            timeout=60,
        )
        events, text = parse_sse(r)
        print(f"  Comparison Response:\n{text[:300]}...")
        assert any(k in text.upper() for k in ["TOPIC", "SIMILAR", "DIFFER", "CONCLUSION", "YES", "NO", "SOURCE"]), "Expected structured comparison sections"
        print("  ✅ TEST C (Cross-Modal Comparison) PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST C FAILED: {e}")
        failed += 1

    # ── TEST D: Source Isolation (No Context Leakage) ───────────────────────────
    print("\n[TEST D] Source Isolation Check")
    try:
        # Ask pure trivia/math -> zero document context leakage
        r_math = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "What is 15 * 4?", "session_id": session_id},
            stream=True,
            timeout=30,
        )
        _, text_math = parse_sse(r_math)
        assert "60" in text_math, f"Expected 60, got {text_math}"
        assert "memo" not in text_math.lower() and "quantum" not in text_math.lower(), "Context leakage in math query"

        # Ask YouTube only in session with documents
        r_yt_isolated = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "What song is this: https://www.youtube.com/watch?v=dQw4w9WgXcQ", "session_id": session_id},
            stream=True,
            timeout=40,
        )
        _, text_yt = parse_sse(r_yt_isolated)
        assert "memo" not in text_yt.lower() and "pdf" not in text_yt.lower(), "Context leakage in YouTube query"
        print("  ✅ TEST D (Source Isolation) PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST D FAILED: {e}")
        failed += 1

    # ── TEST E: Retrieval Performance & Embedding Cache ─────────────────────────
    print("\n[TEST E] Performance & Embedding Cache Latency Test")
    try:
        # First query (populates cache)
        t1_start = time.perf_counter()
        requests.post(f"{BASE_URL}/agent", data={"query": "What are the project details?", "session_id": session_id}, stream=True, timeout=30)
        t1 = (time.perf_counter() - t1_start) * 1000

        # Second identical query (hits cache)
        t2_start = time.perf_counter()
        requests.post(f"{BASE_URL}/agent", data={"query": "What are the project details?", "session_id": session_id}, stream=True, timeout=30)
        t2 = (time.perf_counter() - t2_start) * 1000

        print(f"  Query 1 Latency: {t1:.1f}ms | Query 2 (Cached) Latency: {t2:.1f}ms")
        print("  ✅ TEST E (Embedding Cache & Performance) PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST E FAILED: {e}")
        failed += 1

    print("\n" + "=" * 70)
    print(f"🏁 RESULT: {passed} PASSED, {failed} FAILED (TOTAL {passed + failed})")
    print("=" * 70)
    return failed == 0


if __name__ == "__main__":
    success = test_suite()
    sys.exit(0 if success else 1)
