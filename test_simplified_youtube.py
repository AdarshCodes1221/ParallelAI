#!/usr/bin/env python3
"""
Test: Simplified YouTube Workflow - One-line Summary
Demonstrates the new workflow that returns only a one-line summary.
"""

from backend.services.youtube_fetcher import YouTubeFetcher
from backend.services.gemini_service import GeminiService
import logging
import os

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger()

# Load API key from environment
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    try:
        with open("backend/.env") as f:
            for line in f:
                if line.startswith("GEMINI_API_KEY="):
                    api_key = line.split("=")[1].strip()
                    break
    except:
        pass

if not api_key:
    print("❌ GEMINI_API_KEY not found. Set it in backend/.env or environment.")
    exit(1)

GeminiService.configure(api_key)

print("=" * 80)
print("TEST: Simplified YouTube Workflow - One-line Summary Only")
print("=" * 80)

test_urls = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # Rick Roll (should have transcript)
]

for url in test_urls:
    print(f"\n{'─' * 80}")
    print(f"Testing URL: {url}")
    print(f"{'─' * 80}")
    
    # Step 1: Fetch transcript
    print("\n[Step 1] Fetching YouTube transcript...")
    transcript = YouTubeFetcher.fetch_transcript(url)
    
    if not transcript or transcript.startswith("TRANSCRIPT_FETCH_FAILED:"):
        print(f"❌ FAILED: Could not retrieve video transcript.")
        print(f"   Result: ⚠️ Could not retrieve video transcript.")
        continue
    
    print(f"✅ Transcript retrieved: {len(transcript)} characters")
    print(f"   Preview: {transcript[:150]}...")
    
    # Step 2: Generate one-line summary
    print("\n[Step 2] Generating one-line summary...")
    summary_prompt = f"Summarize this video transcript in exactly ONE sentence (maximum 25 words):\n\n{transcript}"
    
    try:
        one_line_summary = GeminiService.generate_content(
            summary_prompt,
            api_key=api_key,
            model_name="gemini-2.5-flash"
        )
        
        if not one_line_summary or one_line_summary.startswith("REAL GEMINI ERROR"):
            print(f"❌ FAILED: Could not generate summary")
            print(f"   Result: ⚠️ Could not retrieve video transcript.")
        else:
            print(f"✅ One-line summary generated!")
            print(f"\n   📹 FINAL OUTPUT:")
            print(f"   {one_line_summary.strip()}")
            
            # Verify it's actually one line and reasonable length
            lines = one_line_summary.strip().split('\n')
            if len(lines) == 1 and len(one_line_summary.strip()) < 150:
                print(f"\n   ✅ Format verified: Single line, {len(one_line_summary.strip())} characters")
            else:
                print(f"\n   ⚠️  Note: Generated {len(lines)} lines, {len(one_line_summary.strip())} characters")
                
    except Exception as e:
        print(f"❌ EXCEPTION: {type(e).__name__}: {str(e)}")
        print(f"   Result: ⚠️ Could not retrieve video transcript.")

print(f"\n{'=' * 80}")
print("TEST COMPLETE")
print(f"{'=' * 80}")
print("\nExpected behavior:")
print("✅ Fetch YouTube transcript from URL")
print("✅ Send transcript to Gemini with one-line summary prompt")
print("✅ Return ONLY the one-line summary (no bullets, no detailed summary)")
print("✅ If transcript fails, return: ⚠️ Could not retrieve video transcript.")
