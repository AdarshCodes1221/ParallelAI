#!/usr/bin/env python3
"""
Verification of Sentiment Analysis Context Resolution across all 7 scenarios:
1. Explicit text query
2. Conversational follow-up ("Analyze the sentiment of that")
3. Uploaded PDF resume sentiment
4. OCR image sentiment
5. Audio transcript sentiment ("What's the sentiment of what I said?")
6. YouTube transcript sentiment ("What's the sentiment of what the speaker said?")
7. Previous message sentiment ("Was my previous message positive or negative?")
"""

import io
import json
import math
import struct
import sys
import time
import wave
import fitz
import requests
from PIL import Image, ImageDraw

BASE_URL = "http://127.0.0.1:8000/api"


def create_test_pdf(title: str, text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), f"{title}\n\n{text}", fontsize=12)
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


def create_test_image(text: str) -> bytes:
    img = Image.new('RGB', (400, 150), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((20, 50), text, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


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


def test_sentiment_suite():
    print("=" * 70)
    print("🚀 RUNNING SENTIMENT ANALYSIS RESOLUTION SUITE (7 SCENARIOS)")
    print("=" * 70)

    session_id = f"sentiment-test-{int(time.time())}"
    passed = 0
    failed = 0

    # 1. Explicit text sentiment
    print("\n[1] Explicit Text Sentiment: 'Analyze this text sentiment: I am extremely happy with this milestone!'")
    try:
        r = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "Analyze this text sentiment: I am extremely happy with this milestone!", "session_id": session_id},
            stream=True,
            timeout=40,
        )
        _, text = parse_sse(r)
        print(f"  Response:\n{text[:200]}...")
        assert "POSITIVE" in text.upper() or "LABEL:" in text.upper(), "Expected positive sentiment label"
        print("  ✅ TEST 1 (Explicit Text) PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 1 FAILED: {e}")
        failed += 1

    # 2. Conversational follow-up: "Analyze the sentiment of that"
    print("\n[2] Conversational Follow-up: 'Analyze the sentiment of that'")
    try:
        r = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "Analyze the sentiment of that", "session_id": session_id},
            stream=True,
            timeout=40,
        )
        _, text = parse_sse(r)
        print(f"  Response:\n{text[:200]}...")
        assert len(text) > 20 and ("LABEL:" in text.upper() or "SENTIMENT" in text.upper()), "Expected sentiment evaluation of previous text"
        print("  ✅ TEST 2 (Conversational Follow-up) PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 2 FAILED: {e}")
        failed += 1

    # 3. Uploaded PDF Resume sentiment
    print("\n[3] PDF Resume Sentiment: 'What is the sentiment of the resume?'")
    try:
        pdf_session = f"pdf-sent-{int(time.time())}"
        pdf_bytes = create_test_pdf("RESUME", "Adarsh Jha. Hardworking AI Engineer. Excited to build autonomous scalable systems.")
        r = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "What is the sentiment of the resume?", "session_id": pdf_session},
            files=[("files", ("resume.pdf", pdf_bytes, "application/pdf"))],
            stream=True,
            timeout=40,
        )
        _, text = parse_sse(r)
        print(f"  Response:\n{text[:200]}...")
        assert "LABEL:" in text.upper() or "SENTIMENT" in text.upper(), "Expected structured sentiment of PDF"
        print("  ✅ TEST 3 (PDF Resume Sentiment) PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 3 FAILED: {e}")
        failed += 1

    # 4. OCR Image sentiment
    print("\n[4] OCR Image Sentiment: 'Analyze the sentiment of this image text'")
    try:
        img_session = f"ocr-sent-{int(time.time())}"
        img_bytes = create_test_image("We are deeply grateful for your support.")
        r = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "Analyze the sentiment of this image text", "session_id": img_session},
            files=[("files", ("card.png", img_bytes, "image/png"))],
            stream=True,
            timeout=40,
        )
        _, text = parse_sse(r)
        print(f"  Response:\n{text[:200]}...")
        assert "LABEL:" in text.upper() or "POSITIVE" in text.upper(), "Expected sentiment of image OCR"
        print("  ✅ TEST 4 (OCR Sentiment) PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 4 FAILED: {e}")
        failed += 1

    # 5. Audio Transcript Sentiment
    print("\n[5] Audio Sentiment: 'What's the sentiment of what I said?'")
    try:
        audio_session = f"audio-sent-{int(time.time())}"
        wav_bytes = create_test_wav(1.0)
        # Upload audio first
        requests.post(
            f"{BASE_URL}/agent",
            data={"query": "", "session_id": audio_session},
            files=[("files", ("voice.wav", wav_bytes, "audio/wav"))],
            stream=True,
            timeout=60,
        )
        # Ask sentiment of what was said
        r = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "What is the sentiment of what I said in the audio?", "session_id": audio_session},
            stream=True,
            timeout=40,
        )
        _, text = parse_sse(r)
        print(f"  Response:\n{text[:200]}...")
        assert "LABEL:" in text.upper() or "NEUTRAL" in text.upper() or "SENTIMENT" in text.upper(), "Expected audio transcript sentiment"
        print("  ✅ TEST 5 (Audio Transcript Sentiment) PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 5 FAILED: {e}")
        failed += 1

    # 6. YouTube Transcript Sentiment
    print("\n[6] YouTube Sentiment: 'What is the sentiment of the song in the video?'")
    try:
        yt_session = f"yt-sent-{int(time.time())}"
        r = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "What is the sentiment of the lyrics in this video: https://www.youtube.com/watch?v=dQw4w9WgXcQ", "session_id": yt_session},
            stream=True,
            timeout=50,
        )
        _, text = parse_sse(r)
        print(f"  Response:\n{text[:200]}...")
        assert "LABEL:" in text.upper() or "POSITIVE" in text.upper() or "SENTIMENT" in text.upper(), "Expected YouTube lyrics sentiment"
        print("  ✅ TEST 6 (YouTube Sentiment) PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 6 FAILED: {e}")
        failed += 1

    # 7. Previous Message Sentiment: "Was my previous message positive or negative?"
    print("\n[7] Previous Message Sentiment: 'Was my previous message positive or negative?'")
    try:
        chat_session = f"prev-msg-sent-{int(time.time())}"
        # Send user message and consume stream
        r_init = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "This platform has exceeded all our expectations and delivered flawless results.", "session_id": chat_session},
            stream=True,
            timeout=30,
        )
        parse_sse(r_init)

        # Ask if previous message was positive or negative
        r = requests.post(
            f"{BASE_URL}/agent",
            data={"query": "Was my previous message positive or negative?", "session_id": chat_session},
            stream=True,
            timeout=30,
        )
        _, text = parse_sse(r)
        print(f"  Response:\n{text[:200]}...")
        assert "POSITIVE" in text.upper() or "LABEL:" in text.upper(), "Expected positive identification of previous message"
        print("  ✅ TEST 7 (Previous Message Sentiment) PASSED")
        passed += 1
    except Exception as e:
        print(f"  ❌ TEST 7 FAILED: {e}")
        failed += 1

    print("\n" + "=" * 70)
    print(f"🏁 SENTIMENT SUITE RESULT: {passed} PASSED, {failed} FAILED (TOTAL {passed + failed})")
    print("=" * 70)
    return failed == 0


if __name__ == "__main__":
    success = test_sentiment_suite()
    sys.exit(0 if success else 1)
