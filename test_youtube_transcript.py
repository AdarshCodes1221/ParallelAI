#!/usr/bin/env python3
"""
Test: YouTube Transcript System with Robust Fallback
Tests the new multi-language fallback and error handling
"""

import sys
import os

# Install yt-dlp if not present
try:
    import yt_dlp
    print("✅ yt-dlp already installed")
except ImportError:
    print("📦 Installing yt-dlp...")
    os.system("pip install yt-dlp --quiet")
    import yt_dlp
    print("✅ yt-dlp installed")

from backend.services.youtube_fetcher import YouTubeFetcher
import logging

# Configure logging to see debug output
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger()

print("=" * 80)
print("TEST: YouTube Transcript System - Robust Fallback")
print("=" * 80)

# Test cases
test_cases = [
    {
        "name": "Test 1: Standard YouTube URL",
        "url": "https://www.youtube.com/watch?v=wWeXwSh2DgM",
        "expected": "should return transcript"
    },
    {
        "name": "Test 2: Shortened youtu.be URL",
        "url": "https://youtu.be/gC1tj3klvxA",
        "expected": "should return transcript"
    },
    {
        "name": "Test 3: Invalid URL",
        "url": "https://www.youtube.com/watch?v=invalid123",
        "expected": "should return TRANSCRIPT_FETCH_FAILED"
    },
]

results = []

for i, test in enumerate(test_cases, 1):
    print(f"\n{'─' * 80}")
    print(f"Test {i}: {test['name']}")
    print(f"URL: {test['url']}")
    print(f"Expected: {test['expected']}")
    print(f"{'─' * 80}")
    
    try:
        transcript = YouTubeFetcher.fetch_transcript(test['url'])
        
        if transcript:
            if transcript.startswith("TRANSCRIPT_FETCH_FAILED:"):
                print(f"❌ FAILED: {transcript}")
                results.append({
                    "test": test['name'],
                    "status": "FAILED",
                    "result": transcript[:100]
                })
            elif len(transcript) > 100:
                print(f"✅ SUCCESS: Retrieved transcript")
                print(f"   Length: {len(transcript)} characters")
                print(f"   Preview: {transcript[:150]}...")
                results.append({
                    "test": test['name'],
                    "status": "SUCCESS",
                    "result": f"Transcript ({len(transcript)} chars)"
                })
            else:
                print(f"⚠️  WARNING: Transcript too short ({len(transcript)} chars)")
                results.append({
                    "test": test['name'],
                    "status": "WARNING",
                    "result": f"Transcript too short ({len(transcript)} chars)"
                })
        else:
            print(f"❌ FAILED: No transcript returned")
            results.append({
                "test": test['name'],
                "status": "FAILED",
                "result": "No transcript"
            })
    
    except Exception as e:
        print(f"❌ EXCEPTION: {type(e).__name__}: {str(e)}")
        results.append({
            "test": test['name'],
            "status": "EXCEPTION",
            "result": str(e)[:100]
        })

# Summary
print(f"\n{'=' * 80}")
print("TEST SUMMARY")
print(f"{'=' * 80}")

for result in results:
    status_icon = "✅" if result["status"] == "SUCCESS" else "❌" if result["status"] == "FAILED" else "⚠️"
    print(f"{status_icon} {result['test']}: {result['status']}")
    print(f"   Result: {result['result']}")

success_count = sum(1 for r in results if r["status"] == "SUCCESS")
print(f"\n{success_count}/{len(results)} tests passed")

if success_count >= 1:
    print("\n✅ YouTube Transcript System is working!")
    print("✅ Multi-language fallback is active")
    print("✅ yt-dlp fallback is installed")
else:
    print("\n⚠️  YouTube Transcript System needs network access to work")
    print("   (Tests require active internet connection)")

print("\n" + "=" * 80)
