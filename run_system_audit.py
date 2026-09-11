import os
import sys
import json
import time
import uuid
import re
import requests
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import wave
import struct

BASE_URL = "http://localhost:8000"
MAILPIT_URL = "http://localhost:8025"
OLLAMA_URL = "http://localhost:11434"

results = {}

def log_section(title):
    print("\n" + "="*60)
    print(f"=== {title}")
    print("="*60)

def test_auth_and_user_flow():
    log_section("6. AUTHENTICATION & USER FLOW")
    res = {}
    session = requests.Session()
    email_a = f"usera_{uuid.uuid4().hex[:8]}@example.com"
    pwd_a = "SecretP@ss1234"
    
    # A. Signup
    signup_resp = session.post(f"{BASE_URL}/api/auth/signup", json={"email": email_a, "password": pwd_a, "name": "User Alpha"})
    res["signup_status"] = signup_resp.status_code
    res["signup_body"] = signup_resp.json()
    res["signup_sets_cookie"] = "session_token" in session.cookies
    print(f"A. Signup: status={signup_resp.status_code}, sets_cookie={res['signup_sets_cookie']}")

    # B. Auto-auth check (me endpoint should fail 401)
    me_before_login = session.get(f"{BASE_URL}/api/auth/me")
    res["me_before_login_status"] = me_before_login.status_code
    print(f"B. /api/auth/me before login: status={me_before_login.status_code} (Expected 401)")

    # C. Login
    login_resp = session.post(f"{BASE_URL}/api/auth/login", json={"email": email_a, "password": pwd_a})
    res["login_status"] = login_resp.status_code
    res["login_body"] = login_resp.json()
    res["session_cookie_set"] = "session_token" in session.cookies
    res["csrf_cookie_set"] = "csrf_token" in session.cookies
    csrf_token = session.cookies.get("csrf_token")
    print(f"C. Login: status={login_resp.status_code}, session_cookie={res['session_cookie_set']}, csrf_cookie={res['csrf_cookie_set']}")

    # D. Me check
    me_after_login = session.get(f"{BASE_URL}/api/auth/me")
    res["me_after_login_status"] = me_after_login.status_code
    res["me_user"] = me_after_login.json() if me_after_login.status_code == 200 else None
    user_a_id = res["me_user"]["user"]["id"] if res["me_user"] and "user" in res["me_user"] else (res["me_user"].get("id") if res["me_user"] else None)
    print(f"D. /api/auth/me after login: status={me_after_login.status_code}, user_id={user_a_id}")

    # E. Logout
    logout_resp = session.post(f"{BASE_URL}/api/auth/logout", headers={"X-CSRF-Token": csrf_token or ""})
    res["logout_status"] = logout_resp.status_code
    me_after_logout = session.get(f"{BASE_URL}/api/auth/me")
    res["me_after_logout_status"] = me_after_logout.status_code
    print(f"E. Logout: status={logout_resp.status_code}, me_after_logout={me_after_logout.status_code} (Expected 401)")

    # F. Login with wrong password
    wrong_pwd_resp = session.post(f"{BASE_URL}/api/auth/login", json={"email": email_a, "password": "WrongPassword123!"})
    res["wrong_password_status"] = wrong_pwd_resp.status_code
    print(f"F. Login wrong password: status={wrong_pwd_resp.status_code} (Expected 401)")

    # G. Duplicate signup
    dup_signup_resp = session.post(f"{BASE_URL}/api/auth/signup", json={"email": email_a, "password": pwd_a})
    res["duplicate_signup_status"] = dup_signup_resp.status_code
    print(f"G. Duplicate signup: status={dup_signup_resp.status_code} (Expected 400 or 409)")

    results["auth_flow"] = res
    return email_a, pwd_a

def test_forgot_password_and_mailpit(email_a, old_pwd):
    log_section("7. FORGOT PASSWORD & MAILPIT FLOW")
    res = {}
    session = requests.Session()
    
    # 1. Forgot password request
    forgot_resp = session.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": email_a})
    res["forgot_status"] = forgot_resp.status_code
    res["forgot_body"] = forgot_resp.json()
    res["leaks_token"] = "token" in str(forgot_resp.text).lower() and "reset" not in str(forgot_resp.text).lower()
    print(f"1. Forgot password request: status={forgot_resp.status_code}, leaks_token={res['leaks_token']}")

    # 2. Check Mailpit
    time.sleep(1.5)
    mailpit_resp = requests.get(f"{MAILPIT_URL}/api/v1/messages")
    res["mailpit_status"] = mailpit_resp.status_code
    messages = mailpit_resp.json().get("messages", [])
    print(f"2. Mailpit messages count: {len(messages)}")
    
    reset_token = None
    target_msg = None
    for msg in messages:
        recipients = [t.get("Address", "") for t in msg.get("To", [])]
        if email_a in recipients:
            target_msg = msg
            break
            
    if target_msg:
        msg_id = target_msg["ID"]
        msg_detail = requests.get(f"{MAILPIT_URL}/api/v1/message/{msg_id}").json()
        body_text = msg_detail.get("Text", "") + " " + msg_detail.get("HTML", "")
        # Extract token
        match = re.search(r"token=([a-zA-Z0-9_\-]+)", body_text)
        if match:
            reset_token = match.group(1)
        res["email_found"] = True
        res["reset_token_found"] = bool(reset_token)
        print(f"3. Found email to {email_a}, reset_token={reset_token[:10]}...")
    else:
        res["email_found"] = False
        res["reset_token_found"] = False
        print("❌ Could not find reset email in Mailpit")

    # 3. Reset password
    new_pwd = "NewSecurePassword456!"
    if reset_token:
        reset_resp = session.post(f"{BASE_URL}/api/auth/reset-password", json={"token": reset_token, "new_password": new_pwd})
        res["reset_status"] = reset_resp.status_code
        print(f"4. Password reset execution: status={reset_resp.status_code}")

        # 4. Old password fails
        old_login = session.post(f"{BASE_URL}/api/auth/login", json={"email": email_a, "password": old_pwd})
        res["old_password_login_status"] = old_login.status_code
        print(f"5. Old password login: status={old_login.status_code} (Expected 401)")

        # 5. New password succeeds
        new_login = session.post(f"{BASE_URL}/api/auth/login", json={"email": email_a, "password": new_pwd})
        res["new_password_login_status"] = new_login.status_code
        print(f"6. New password login: status={new_login.status_code} (Expected 200)")

        # 6. Reusing token fails
        reuse_resp = session.post(f"{BASE_URL}/api/auth/reset-password", json={"token": reset_token, "new_password": "ThirdPassword789!"})
        res["token_reuse_status"] = reuse_resp.status_code
        print(f"7. Token reuse: status={reuse_resp.status_code} (Expected 400)")

        # 7. Invalid token fails
        invalid_resp = session.post(f"{BASE_URL}/api/auth/reset-password", json={"token": "invalid-random-token-xyz", "new_password": "ThirdPassword789!"})
        res["invalid_token_status"] = invalid_resp.status_code
        print(f"8. Invalid token: status={invalid_resp.status_code} (Expected 400)")

    results["forgot_password"] = res

def test_security_and_tenant_isolation():
    log_section("8 & 9. SECURITY & MULTI-TENANT ISOLATION")
    res = {}
    # Create User A and User B
    s_a = requests.Session()
    s_b = requests.Session()
    
    email_a = f"tenant_a_{uuid.uuid4().hex[:8]}@example.com"
    email_b = f"tenant_b_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "IsolationPassword123!"
    
    s_a.post(f"{BASE_URL}/api/auth/signup", json={"email": email_a, "password": pwd, "name": "Tenant A"})
    s_a.post(f"{BASE_URL}/api/auth/login", json={"email": email_a, "password": pwd})
    csrf_a = s_a.cookies.get("csrf_token")
    
    s_b.post(f"{BASE_URL}/api/auth/signup", json={"email": email_b, "password": pwd, "name": "Tenant B"})
    s_b.post(f"{BASE_URL}/api/auth/login", json={"email": email_b, "password": pwd})
    csrf_b = s_b.cookies.get("csrf_token")

    # User A creates a chat session
    chat_a = s_a.post(f"{BASE_URL}/api/sessions", json={"title": "Confidential Project A"}, headers={"X-CSRF-Token": csrf_a}).json()
    chat_a_id = chat_a["id"]
    print(f"User A created chat session: {chat_a_id}")

    # User B tries to read User A's session
    b_reads_a = s_b.get(f"{BASE_URL}/api/sessions/{chat_a_id}")
    res["b_reads_a_session_status"] = b_reads_a.status_code
    print(f"User B accesses User A's session: status={b_reads_a.status_code} (Expected 404 or 403)")

    # User B tries to list sessions
    b_sessions = s_b.get(f"{BASE_URL}/api/sessions").json()
    b_session_ids = [s.get("id") or s.get("session_key") for s in (b_sessions if isinstance(b_sessions, list) else b_sessions.get("sessions", []))]
    res["chat_a_in_b_list"] = chat_a_id in b_session_ids
    print(f"User A's chat in User B's session list: {res['chat_a_in_b_list']} (Expected False)")

    # Unauthenticated access to protected routes
    anon = requests.Session()
    anon_me = anon.get(f"{BASE_URL}/api/auth/me")
    anon_sessions = anon.get(f"{BASE_URL}/api/sessions")
    res["anon_me_status"] = anon_me.status_code
    res["anon_sessions_status"] = anon_sessions.status_code
    print(f"Anonymous access /api/auth/me: {anon_me.status_code}, /api/sessions: {anon_sessions.status_code} (Expected 401)")

    results["multi_tenant_isolation"] = res
    return s_a, csrf_a, chat_a_id

def test_ollama():
    log_section("12. OLLAMA / LLM CHECK")
    res = {}
    try:
        tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).json()
        model_names = [m["name"] for m in tags.get("models", [])]
        res["models_found"] = model_names
        print(f"Ollama models found: {model_names}")
        
        # Test embeddings
        emb_resp = requests.post(f"{OLLAMA_URL}/api/embeddings", json={
            "model": "nomic-embed-text",
            "prompt": "Parallel AI vector test"
        }, timeout=10).json()
        emb_len = len(emb_resp.get("embedding", []))
        res["embedding_dimension"] = emb_len
        print(f"Nomic embedding dimension: {emb_len} (Expected 768)")

        # Test generation
        gen_resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": "llama3.2:3b",
            "prompt": "Respond with the single word: READY",
            "stream": False
        }, timeout=15).json()
        res["generation_text"] = gen_resp.get("response", "").strip()
        print(f"Llama generation response: {res['generation_text']}")
    except Exception as e:
        res["error"] = str(e)
        print(f"❌ Ollama check error: {e}")

    results["ollama"] = res

def create_factual_test_pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import inch
    
    pdf_path = "temp_uploads/audit_factual_test.pdf"
    os.makedirs("temp_uploads", exist_ok=True)
    c = canvas.Canvas(pdf_path, pagesize=letter)
    width, height = letter
    
    c.setFont("Helvetica-Bold", 16)
    c.drawString(inch, height - inch, "Mission Olympus Technical Report")
    
    c.setFont("Helvetica", 12)
    c.drawString(inch, height - 1.6*inch, "Fact 1: The Project Olympus launch date is October 24, 2026.")
    c.drawString(inch, height - 2.0*inch, "Fact 2: The chief architect for the orbital array is Dr. Elena Rostova in Geneva.")
    c.drawString(inch, height - 2.4*inch, "Fact 3: Total solar harvest was 15,000 megawatt-hours across 75 collectors.")
    c.drawString(inch, height - 2.8*inch, "This yields an average output of exactly 200 megawatt-hours per collector.")
    c.drawString(inch, height - 3.2*inch, "The telemetry data was calibrated by technician Marcus Reed in Boston.")
    c.save()
    return pdf_path

def test_rag_and_ingestion(s_a, csrf_a, chat_a_id):
    log_section("13, 14. RAG END-TO-END & PDF PARSER")
    res = {}
    pdf_path = create_factual_test_pdf()
    
    # Test standalone /api/pdf
    with open(pdf_path, "rb") as f:
        pdf_resp = requests.post(f"{BASE_URL}/api/pdf", files={"file": ("audit_factual_test.pdf", f, "application/pdf")})
    res["standalone_pdf_status"] = pdf_resp.status_code
    res["standalone_pdf_text"] = pdf_resp.json().get("text", "") if pdf_resp.status_code == 200 else ""
    print(f"Standalone /api/pdf: status={pdf_resp.status_code}, extracted_chars={len(res['standalone_pdf_text'])}")

    # Ingest document via /api/agent with PDF upload
    with open(pdf_path, "rb") as f:
        agent_ingest = s_a.post(
            f"{BASE_URL}/api/agent",
            data={
                "session_id": chat_a_id,
                "query": "Please analyze this document and summarize what it is about.",
                "model": "llama3.2:3b",
            },
            files={"files": ("audit_factual_test.pdf", f, "application/pdf")},
            headers={"X-CSRF-Token": csrf_a},
            stream=True,
            timeout=60
        )
    
    raw_sse = []
    for line in agent_ingest.iter_lines():
        if line:
            raw_sse.append(line.decode("utf-8", errors="ignore"))
    res["ingest_sse_lines"] = len(raw_sse)
    print(f"Agent ingestion SSE response lines: {len(raw_sse)}")

    time.sleep(2) # Allow Redis indexing

    # Question A (Exact fact)
    q_a = "What is the Project Olympus launch date?"
    ans_a_resp = s_a.post(
        f"{BASE_URL}/api/agent",
        data={"session_id": chat_a_id, "query": q_a, "model": "llama3.2:3b"},
        headers={"X-CSRF-Token": csrf_a},
        stream=True,
        timeout=60
    )
    tokens_a = []
    for line in ans_a_resp.iter_lines():
        if line:
            txt = line.decode("utf-8", errors="ignore")
            if txt.startswith("data: "):
                try:
                    payload = json.loads(txt[6:])
                    if payload.get("type") == "token":
                        tokens_a.append(payload.get("token", ""))
                except Exception:
                    pass
    full_ans_a = "".join(tokens_a)
    res["q_a"] = q_a
    res["ans_a"] = full_ans_a
    res["ans_a_correct"] = "october 24" in full_ans_a.lower() and "2026" in full_ans_a.lower()
    print(f"Question A: '{q_a}'\nAnswer: {full_ans_a}\nCorrect: {res['ans_a_correct']}")

    # Question B (Cross-section fact)
    q_b = "Who is the chief architect for the orbital array and where are they located?"
    ans_b_resp = s_a.post(
        f"{BASE_URL}/api/agent",
        data={"session_id": chat_a_id, "query": q_b, "model": "llama3.2:3b"},
        headers={"X-CSRF-Token": csrf_a},
        stream=True,
        timeout=60
    )
    tokens_b = []
    for line in ans_b_resp.iter_lines():
        if line:
            txt = line.decode("utf-8", errors="ignore")
            if txt.startswith("data: "):
                try:
                    payload = json.loads(txt[6:])
                    if payload.get("type") == "token":
                        tokens_b.append(payload.get("token", ""))
                except Exception:
                    pass
    full_ans_b = "".join(tokens_b)
    res["q_b"] = q_b
    res["ans_b"] = full_ans_b
    res["ans_b_correct"] = "elena" in full_ans_b.lower() and ("rostova" in full_ans_b.lower() or "geneva" in full_ans_b.lower())
    print(f"Question B: '{q_b}'\nAnswer: {full_ans_b}\nCorrect: {res['ans_b_correct']}")

    # Question C (Not in document)
    q_c = "What is the capital of Mars and what is its current population?"
    ans_c_resp = s_a.post(
        f"{BASE_URL}/api/agent",
        data={"session_id": chat_a_id, "query": q_c, "model": "llama3.2:3b"},
        headers={"X-CSRF-Token": csrf_a},
        stream=True,
        timeout=60
    )
    tokens_c = []
    for line in ans_c_resp.iter_lines():
        if line:
            txt = line.decode("utf-8", errors="ignore")
            if txt.startswith("data: "):
                try:
                    payload = json.loads(txt[6:])
                    if payload.get("type") == "token":
                        tokens_c.append(payload.get("token", ""))
                except Exception:
                    pass
    full_ans_c = "".join(tokens_c)
    res["q_c"] = q_c
    res["ans_c"] = full_ans_c
    print(f"Question C (Not in doc): '{q_c}'\nAnswer: {full_ans_c}")

    # Numerical question
    q_num = "What was the average output per collector?"
    ans_num_resp = s_a.post(
        f"{BASE_URL}/api/agent",
        data={"session_id": chat_a_id, "query": q_num, "model": "llama3.2:3b"},
        headers={"X-CSRF-Token": csrf_a},
        stream=True,
        timeout=60
    )
    tokens_num = []
    for line in ans_num_resp.iter_lines():
        if line:
            txt = line.decode("utf-8", errors="ignore")
            if txt.startswith("data: "):
                try:
                    payload = json.loads(txt[6:])
                    if payload.get("type") == "token":
                        tokens_num.append(payload.get("token", ""))
                except Exception:
                    pass
    full_ans_num = "".join(tokens_num)
    res["q_num"] = q_num
    res["ans_num"] = full_ans_num
    res["ans_num_correct"] = "200" in full_ans_num
    print(f"Numerical Question: '{q_num}'\nAnswer: {full_ans_num}\nCorrect: {res['ans_num_correct']}")

    results["rag_and_pdf"] = res

def create_test_ocr_image():
    img_path = "temp_uploads/audit_ocr_test.png"
    os.makedirs("temp_uploads", exist_ok=True)
    img = Image.new('RGB', (600, 150), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    text = "PARALLEL AI OCR VERIFICATION 2026"
    d.text((30, 60), text, fill=(0, 0, 0))
    img.save(img_path)
    return img_path

def test_ocr():
    log_section("15. OCR TEST")
    res = {}
    img_path = create_test_ocr_image()
    with open(img_path, "rb") as f:
        ocr_resp = requests.post(f"{BASE_URL}/api/ocr", files={"file": ("audit_ocr_test.png", f, "image/png")})
    res["status_code"] = ocr_resp.status_code
    body = ocr_resp.json() if ocr_resp.status_code == 200 else {}
    res["extracted_text"] = body.get("text", "")
    res["confidence"] = body.get("confidence", 0)
    print(f"OCR response status={ocr_resp.status_code}, text='{res['extracted_text'].strip()}', confidence={res['confidence']}")
    results["ocr"] = res

def test_mime_handling(s_a, csrf_a, chat_a_id):
    log_section("16. TEXT DOCUMENT / MIME HANDLING")
    res = {}
    txt_path = "temp_uploads/audit_test.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("This is a plain text document test.")
        
    with open(txt_path, "rb") as f:
        agent_txt = s_a.post(
            f"{BASE_URL}/api/agent",
            data={"session_id": chat_a_id, "query": "Read this text file.", "model": "llama3.2:3b"},
            files={"files": ("audit_test.txt", f, "text/plain")},
            headers={"X-CSRF-Token": csrf_a},
            stream=True,
            timeout=30
        )
    sse_output = []
    for line in agent_txt.iter_lines():
        if line:
            sse_output.append(line.decode("utf-8", errors="ignore"))
    res["agent_txt_sse"] = sse_output[:5]
    print(f"Plain text upload response: {sse_output[:3]}")
    results["mime_handling"] = res

def create_synthetic_wav():
    wav_path = "temp_uploads/audit_test.wav"
    os.makedirs("temp_uploads", exist_ok=True)
    with wave.open(wav_path, "w") as wav_file:
        wav_file.setnchannels(1) # mono
        wav_file.setsampwidth(2) # 16-bit
        wav_file.setframerate(16000) # 16kHz
        # 1.5 seconds of silence/gentle sine
        for i in range(24000):
            val = int(1000 * (i % 32 < 16))
            wav_file.writeframes(struct.pack('<h', val))
    return wav_path

def test_audio():
    log_section("17. AUDIO / VOICE TEST")
    res = {}
    wav_path = create_synthetic_wav()
    with open(wav_path, "rb") as f:
        audio_resp = requests.post(f"{BASE_URL}/api/audio", files={"file": ("audit_test.wav", f, "audio/wav")})
    res["status_code"] = audio_resp.status_code
    res["body"] = audio_resp.json() if audio_resp.status_code == 200 else {}
    print(f"Audio STT response status={audio_resp.status_code}, meta={res['body'].get('meta')}, transcript='{res['body'].get('transcript')}'")
    results["audio"] = res

def test_youtube(s_a, csrf_a):
    log_section("18. YOUTUBE TEST")
    res = {}
    # 1. Invalid URL
    inv_resp = s_a.post(f"{BASE_URL}/api/youtube", json={"url": "https://not-youtube.com/watch?v=123"}, headers={"X-CSRF-Token": csrf_a})
    res["invalid_url_status"] = inv_resp.status_code
    res["invalid_url_body"] = inv_resp.json() if inv_resp.status_code == 200 else {}
    print(f"YouTube invalid URL: status={inv_resp.status_code}, body={res['invalid_url_body']}")

    # 2. Real YouTube URL
    valid_resp = s_a.post(f"{BASE_URL}/api/youtube", json={"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"}, headers={"X-CSRF-Token": csrf_a})
    res["valid_url_status"] = valid_resp.status_code
    res["valid_url_body"] = valid_resp.json() if valid_resp.status_code == 200 else {}
    print(f"YouTube valid URL: status={valid_resp.status_code}, body_status={res['valid_url_body'].get('status')}")
    results["youtube"] = res

def test_summarization_sentiment_code(s_a, csrf_a):
    log_section("19, 20, 21. SUMMARIZATION, SENTIMENT & CODE ANALYSIS")
    res = {}
    
    # Summarization
    sample_text = (
        "Artificial intelligence is rapidly transforming global industry. From healthcare diagnostics to autonomous "
        "logistics, machine learning models analyze complex data streams with unprecedented accuracy. Organizations "
        "must invest in scalable data pipelines and robust governance frameworks. Security and multi-tenant isolation "
        "are paramount when deploying AI assistants. Overall, the technology provides enormous productivity gains when managed responsibly."
    )
    sum_resp = s_a.post(f"{BASE_URL}/api/summary", json={"text": sample_text}, headers={"X-CSRF-Token": csrf_a})
    res["summary_status"] = sum_resp.status_code
    res["summary_body"] = sum_resp.json() if sum_resp.status_code == 200 else {}
    print(f"Summary: status={sum_resp.status_code}, len={len(res['summary_body'].get('summary', ''))}")

    # Sentiment (Positive, Negative, Neutral)
    sent_pos = s_a.post(f"{BASE_URL}/api/sentiment", json={"text": "I absolutely love this product! It has made our engineering workflow so fast and joyful."}, headers={"X-CSRF-Token": csrf_a})
    sent_neg = s_a.post(f"{BASE_URL}/api/sentiment", json={"text": "This service is terrible. It keeps crashing, lost our database records, and the support is completely unresponsive."}, headers={"X-CSRF-Token": csrf_a})
    sent_neu = s_a.post(f"{BASE_URL}/api/sentiment", json={"text": "The server CPU usage is hovering at 45% and memory consumption is 2 gigabytes."}, headers={"X-CSRF-Token": csrf_a})
    res["sent_pos"] = sent_pos.json() if sent_pos.status_code == 200 else {}
    res["sent_neg"] = sent_neg.json() if sent_neg.status_code == 200 else {}
    res["sent_neu"] = sent_neu.json() if sent_neu.status_code == 200 else {}
    print(f"Sentiment Positive: {res['sent_pos'].get('analysis', '')[:100]}")
    print(f"Sentiment Negative: {res['sent_neg'].get('analysis', '')[:100]}")
    print(f"Sentiment Neutral: {res['sent_neu'].get('analysis', '')[:100]}")

    # Code analysis
    buggy_code = (
        "def compute_average(values):\n"
        "    total = sum(values)\n"
        "    return total / len(values) # BUG: ZeroDivisionError when values is empty\n"
    )
    code_resp = s_a.post(f"{BASE_URL}/api/code-analysis", json={"text": buggy_code}, headers={"X-CSRF-Token": csrf_a})
    res["code_status"] = code_resp.status_code
    res["code_body"] = code_resp.json() if code_resp.status_code == 200 else {}
    print(f"Code Analysis: status={code_resp.status_code}, output={res['code_body'].get('analysis', '')[:150]}...")

    results["standalone_intelligence"] = res

def test_upload_limits(s_a, csrf_a):
    log_section("23. FILE UPLOAD LIMITS")
    res = {}
    large_path = "temp_uploads/audit_large_file.bin"
    # Write 55MB (over 50MB limit)
    with open(large_path, "wb") as f:
        f.seek(55 * 1024 * 1024 - 1)
        f.write(b"\0")
        
    with open(large_path, "rb") as f:
        large_resp = s_a.post(f"{BASE_URL}/api/upload", files={"file": ("large.bin", f, "application/octet-stream")}, headers={"X-CSRF-Token": csrf_a})
    res["oversized_upload_status"] = large_resp.status_code
    print(f"Oversized (55MB) file upload: status={large_resp.status_code} (Expected 413 or rejection)")
    if os.path.exists(large_path):
        os.remove(large_path)
    results["upload_limits"] = res

def main():
    print("STARTING PARALLEL AI SYSTEM AUDIT EXECUTION SCRIPT...")
    email_a, pwd_a = test_auth_and_user_flow()
    test_forgot_password_and_mailpit(email_a, pwd_a)
    s_a, csrf_a, chat_a_id = test_security_and_tenant_isolation()
    test_ollama()
    test_rag_and_ingestion(s_a, csrf_a, chat_a_id)
    test_ocr()
    test_mime_handling(s_a, csrf_a, chat_a_id)
    test_audio()
    test_youtube(s_a, csrf_a)
    test_summarization_sentiment_code(s_a, csrf_a)
    test_upload_limits(s_a, csrf_a)
    
    with open("temp_uploads/audit_execution_results.json", "w", encoding="utf-8") as out:
        json.dump(results, out, indent=2, default=str)
    print("\n[OK] AUDIT EXECUTION COMPLETE. Results saved to temp_uploads/audit_execution_results.json")

if __name__ == "__main__":
    main()
