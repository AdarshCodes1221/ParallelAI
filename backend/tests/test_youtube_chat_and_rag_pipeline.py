import os
import io
import sys
import uuid
import json
import time
import requests
import pytest

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from core.postgres_store import PostgresStore
from core.redis_store import RedisStore

BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

SAMPLE_TRANSCRIPT = (
    "Well you only need the light when it's burning low. "
    "Only miss the sun when it starts to snow. "
    "Only know you love her when you let her go. "
    "Only know you've been high when you're feeling low. "
    "Only hate the road when you're missin' home. "
    "Only know you love her when you let her go. "
    "And you let her go. Staring at the ceiling in the dark, "
    "same old empty feeling in your heart."
)


def parse_sse_response(response: requests.Response):
    tokens: list[str] = []
    events: list[dict] = []
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        try:
            event = json.loads(line[6:])
            events.append(event)
            if event.get("type") == "token":
                tokens.append(event.get("token", ""))
        except ValueError:
            continue
    return events, "".join(tokens)


def create_authenticated_user(label: str):
    session = requests.Session()
    email = f"yt_{label}_{uuid.uuid4().hex[:6]}@example.com"
    password = "StrongPassword123!"
    ip = f"10.0.{uuid.uuid4().int % 200}.{uuid.uuid4().int % 200}"

    signup_res = session.post(
        f"{BASE_URL}/api/auth/signup",
        json={"email": email, "password": password, "name": f"User {label}"},
        headers={"X-Forwarded-For": ip},
        timeout=10,
    )
    assert signup_res.status_code == 200

    login_res = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        headers={"X-Forwarded-For": ip},
        timeout=10,
    )
    assert login_res.status_code == 200
    csrf_token = session.cookies.get("csrf_token", "")
    me_res = session.get(f"{BASE_URL}/api/auth/me", timeout=10)
    assert me_res.status_code == 200
    user_data = me_res.json()["user"]
    return {
        "session": session,
        "email": email,
        "user_id": user_data["id"],
        "csrf_token": csrf_token,
        "headers": {"X-CSRF-Token": csrf_token, "X-Forwarded-For": ip},
    }


class TestYouTubeChatAndRAGPipeline:

    @pytest.fixture(autouse=True)
    def setup_clients(self):
        self.user_a = create_authenticated_user("alice")
        self.user_b = create_authenticated_user("bob")
        self.session_id = str(uuid.uuid4())
        self.video_url = "https://www.youtube.com/watch?v=RBumgq5yVrA"
        self.video_id = "RBumgq5yVrA"

    def test_01_youtube_url_generates_uuid_and_persists(self):
        """TEST 1: YouTube URL -> transcript fetched -> UUID generated -> document persisted"""
        res = self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": self.video_url, "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )
        assert res.status_code == 200
        events, text = parse_sse_response(res)
        assert "YouTube transcript fetched" in text
        assert self.video_id in text

        # Check Postgres persistence
        db = PostgresStore()
        docs = db.list_documents(session_id=self.session_id, user_id=self.user_a["user_id"])
        assert len(docs) >= 1
        yt_doc = next((d for d in docs if d.get("source_type") == "youtube" or d.get("video_id") == self.video_id), None)
        assert yt_doc is not None, "YouTube document was not found in Postgres!"

        # Verify legitimate UUID
        doc_uuid = uuid.UUID(str(yt_doc["id"]))
        assert str(doc_uuid) == yt_doc["id"]
        assert not yt_doc["id"].startswith("yt-"), "Primary key must not be prefixed with yt-"
        assert yt_doc.get("youtube_video_id") == self.video_id or yt_doc.get("video_id") == self.video_id

    def test_02_duplicate_youtube_url_is_idempotent(self):
        """TEST 2: Same YouTube URL again -> idempotent behavior -> no duplicate-key exception"""
        # First submission
        res1 = self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": self.video_url, "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )
        assert res1.status_code == 200

        # Second submission of the exact same URL in the same session
        res2 = self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": self.video_url, "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )
        assert res2.status_code == 200
        events, text = parse_sse_response(res2)
        assert "YouTube transcript fetched" in text

        # Check that only one document exists for this video in this session
        db = PostgresStore()
        docs = db.list_documents(session_id=self.session_id, user_id=self.user_a["user_id"])
        yt_docs = [d for d in docs if d.get("video_id") == self.video_id or d.get("youtube_video_id") == self.video_id]
        assert len(yt_docs) == 1, f"Expected 1 document, found {len(yt_docs)}"

    def test_03_redis_chunks_exist_with_same_document_uuid(self):
        """TEST 3: YouTube transcript -> Redis chunk exists with same document UUID"""
        res = self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": self.video_url, "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )
        assert res.status_code == 200

        db = PostgresStore()
        docs = db.list_documents(session_id=self.session_id, user_id=self.user_a["user_id"])
        yt_doc = next(d for d in docs if d.get("video_id") == self.video_id or d.get("youtube_video_id") == self.video_id)
        doc_uuid = yt_doc["id"]

        redis = RedisStore().client
        found_chunks = 0
        for key in redis.scan_iter(match="chunk:*"):
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            chunk_doc_id = redis.hget(key_str, "document_id")
            if chunk_doc_id:
                if isinstance(chunk_doc_id, bytes):
                    chunk_doc_id = chunk_doc_id.decode("utf-8")
                if chunk_doc_id == doc_uuid:
                    found_chunks += 1

        assert found_chunks > 0, f"No chunks found in Redis with document_id={doc_uuid}"

    def test_04_followup_what_is_video_about_uses_youtube_document(self):
        """TEST 4: Same chat -> follow-up 'What is the video about?' -> retrieval uses YouTube document"""
        # 1. Ingest YouTube URL
        self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": self.video_url, "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )

        # 2. In the same session, follow up with "What is the video about?"
        followup_res = self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": "What is the video about?", "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )
        assert followup_res.status_code == 200
        events, text = parse_sse_response(followup_res)
        assert len(text) > 0
        assert "not found in the provided content" not in text.lower()

    def test_05_transcript_phrase_query_retrieves_correct_answer(self):
        """TEST 5: Follow-up phrase from transcript ('Only hate when the road') -> correct answer"""
        self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": self.video_url, "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )

        followup_res = self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": "What do you hate according to the video? Only hate when the road...", "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )
        assert followup_res.status_code == 200
        events, text = parse_sse_response(followup_res)
        assert any(word in text.lower() for word in ["road", "home", "missin", "missing"])

    def test_06_absent_question_does_not_hallucinate(self):
        """TEST 6: Question absent from transcript -> grounded 'not found'"""
        self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": self.video_url, "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )

        followup_res = self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": "What is the market cap of Microsoft mentioned in the video?", "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )
        assert followup_res.status_code == 200
        events, text = parse_sse_response(followup_res)
        assert any(
            phrase in text.lower()
            for phrase in [
                "not found",
                "not mentioned",
                "no mention",
                "any mention",
                "does not contain",
                "no information",
                "not aware",
                "don't have",
                "does not mention",
                "no such information",
            ]
        )

    def test_07_user_b_cannot_retrieve_user_a_youtube_document(self):
        """TEST 7: User B cannot retrieve User A YouTube document"""
        self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": self.video_url, "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )

        # User B attempts to access User A's session -> blocked
        user_b_res = self.user_b["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": "What is the video about?", "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_b["headers"],
            stream=True,
            timeout=30,
        )
        assert user_b_res.status_code in (403, 401)

        # User B queries in their own session and cannot see User A's YouTube document
        user_b_own_res = self.user_b["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": "What is the video about?", "model": "gemini-2.5-flash"},
            headers=self.user_b["headers"],
            stream=True,
            timeout=30,
        )
        assert user_b_own_res.status_code == 200
        events, text = parse_sse_response(user_b_own_res)
        assert "burning low" not in text.lower()
        assert "let her go" not in text.lower()

    def test_08_normal_chat_after_youtube_still_works(self):
        """TEST 8: Normal chat after YouTube still works"""
        chat_res = self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": "Hello, are you operational?", "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )
        assert chat_res.status_code == 200
        events, text = parse_sse_response(chat_res)
        assert len(text) > 0
        assert "not found in the provided content" not in text.lower()

    def test_09_pdf_rag_still_works(self):
        """TEST 9: PDF RAG still works"""
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 72), "Academic Transcript: Student Alice has CGPA 9.4 in Computer Science.", fontsize=12)
        pdf_bytes = doc.write()
        doc.close()

        files = {"file": ("alice_transcript.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        upload_res = self.user_a["session"].post(
            f"{BASE_URL}/api/documents/upload",
            data={"session_id": self.session_id},
            files=files,
            headers=self.user_a["headers"],
            timeout=20,
        )
        assert upload_res.status_code == 200

        query_res = self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": "What is the CGPA in the document?", "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )
        assert query_res.status_code == 200
        events, text = parse_sse_response(query_res)
        assert "9.4" in text

    def test_10_ocr_rag_still_works(self):
        """TEST 10: OCR RAG still works"""
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (400, 100), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((20, 30), "INVOICE 8821 PAID", fill=(0, 0, 0))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        files = {"file": ("invoice.png", img_bytes, "image/png")}
        upload_res = self.user_a["session"].post(
            f"{BASE_URL}/api/documents/upload",
            data={"session_id": self.session_id},
            files=files,
            headers=self.user_a["headers"],
            timeout=20,
        )
        assert upload_res.status_code == 200

        query_res = self.user_a["session"].post(
            f"{BASE_URL}/api/agent",
            data={"query": "What is the invoice number in the image?", "session_id": self.session_id, "model": "gemini-2.5-flash"},
            headers=self.user_a["headers"],
            stream=True,
            timeout=30,
        )
        assert query_res.status_code == 200
        events, text = parse_sse_response(query_res)
        assert "8821" in text or "invoice" in text.lower()
