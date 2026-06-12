#!/usr/bin/env python3
"""
Test Case 4 - Cross-Input Multi-Tool Chain
Upload a PDF containing a YouTube URL and request a summary
"""

import requests
import json
import time
import os

BASE_URL = "http://127.0.0.1:8000/api"

# Get API key from environment
API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not API_KEY:
    print("❌ ERROR: GEMINI_API_KEY not set in environment")
    exit(1)

# 1. Upload the PDF with YouTube URL
print("=" * 60)
print("TEST CASE 4 - Cross-Input Multi-Tool Chain")
print("=" * 60)
print(f"\n🔑 Using API Key: {API_KEY[:20]}..." if API_KEY else "❌ No API Key")

pdf_path = "temp_uploads/test_youtube_pdf.pdf"

if not os.path.exists(pdf_path):
    print(f"❌ ERROR: PDF not found at {pdf_path}")
    exit(1)

print(f"\n📄 PDF file: {pdf_path}")

# 2. Send query with intent to extract YouTube summary
print("\n" + "=" * 60)
print("📝 Sending Query: 'Hit the YT URL in this PDF and give me a summary.'")
print("=" * 60)

query = "Hit the YT URL in this PDF and give me a summary."

# Use multipart form data for the agent endpoint
with open(pdf_path, "rb") as f:
    files = [("files", (os.path.basename(pdf_path), f, "application/pdf"))]
    data = {
        "query": query,
        "model": "models/gemini-2.5-flash"
    }
    
    print("\n🔄 Awaiting streaming response from /api/agent endpoint...\n")
    
    try:
        response = requests.post(
            f"{BASE_URL}/agent",
            files=files,
            data=data,
            stream=True,
            timeout=120
        )
        
        print(f"Status: {response.status_code}\n")
        
        if response.status_code != 200:
            print(f"❌ Error: {response.text}")
            exit(1)
        
        # Parse streaming response
        print("📊 STREAMING RESPONSE:")
        print("-" * 60)
        
        full_response = ""
        event_count = 0
        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8') if isinstance(line, bytes) else line
                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    try:
                        parsed = json.loads(data_str)
                        event_count += 1
                        
                        # Handle init event (metadata)
                        if parsed.get("type") == "init":
                            print(f"\n📌 Event {event_count}: INIT (metadata)")
                            if "plan" in parsed:
                                print(f"   Plan steps: {len(parsed['plan'])}")
                                for step in parsed["plan"]:
                                    print(f"   - Step {step['step']}: {step['tool']}")
                            continue
                        
                        # Handle token streaming
                        if "token" in parsed and parsed["token"]:
                            print(parsed["token"], end="", flush=True)
                            full_response += parsed["token"]
                    except json.JSONDecodeError:
                        pass
        
        print("\n" + "-" * 60)
        print("\n✅ Test completed!")
        
        # Check for expected outputs
        expected_outputs = [
            "One-line",
            "summary",
            "bullet",
            "five-sentence"
        ]
        
        print("\n🔍 VALIDATION:")
        for expected in expected_outputs:
            if expected.lower() in full_response.lower():
                print(f"  ✅ Found '{expected}' in output")
            else:
                print(f"  ⚠️  Missing '{expected}' from output")
        
        # Check if YouTube was detected
        if "youtube" in full_response.lower() or "transcript" in full_response.lower():
            print(f"  ✅ YouTube/Transcript content detected")
        else:
            print(f"  ⚠️  No YouTube/Transcript content detected")
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        exit(1)

print("\n" + "=" * 60)
print("TEST COMPLETED")
print("=" * 60)
