"""
RK AI - Automated Developer Mode Test Suite

This script runs a non-interactive, CI/CD-style diagnostic check on
every critical subsystem in the RK AI software stack to ensure parity
and stability.
"""

import os
import sys
import time
from pathlib import Path

# Ensure package context so relative imports work
if __name__ == "__main__" and __package__ is None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    sys.path.insert(0, parent_dir)
    __package__ = "rk_assistant"

from rk_assistant import audio_utils
from rk_assistant.networking import is_online, read_slug
from rk_assistant.config import (
    LAST_AUDIO, BACKEND_BASE_URL, GEMINI_API_KEY, 
    GEMINI_API_KEY_BACKUP, STT_ENGINE, MIC_DEVICE_INDEX
)
from rk_assistant.offline_commands import match_offline_command, process_offline_command
from rk_assistant.gemini_client import classify_intent
from rk_assistant.weather_news import fetch_weather, fetch_news
from rk_assistant.audio_utils_simple import speak

def print_header(title: str):
    print("\n" + "=" * 60)
    print(f" [TEST RUN] {title}")
    print("=" * 60)

def run_all_tests():
    print_header("1. Core Network & Configuration")
    print("Checking Physical Network...")
    online = is_online()
    print(f"Status: {'✅ ONLINE' if online else '❌ OFFLINE (Operating locally)'}")
    
    slug, _ = read_slug()
    print(f"Device Slug:     {slug if slug else '❌ NOT FOUND'}")
    print(f"Backend Server:  {BACKEND_BASE_URL}")
    print(f"STT Engine:      {STT_ENGINE}")
    print(f"Gemini Key 1:    {'✅ CONFIGURED' if GEMINI_API_KEY else '❌ MISSING'}")
    
    print_header("2. Third Party API Integrations")
    if online:
        w = fetch_weather()
        print(f"Weather API: {'✅ PASS' if w else '❌ FAIL'}")
        n = fetch_news()
        print(f"News API:    {'✅ PASS' if len(n) > 50 else '❌ FAIL'}")
    else:
        print("Skipping API tests (Device is Offline).")
        
    print_header("3. Text-to-Speech (TTS) Engine Output")
    print("Attempting to synthesize and play an audible notification beep...")
    try:
        sound_path = str(Path(__file__).parent / "sounds" / "success.mp3")
        if os.path.exists(sound_path):
            audio_utils.play_audio_file(sound_path)
            print("✅ Hardware audio playback succeeded.")
        else:
            print("❌ Test beep sound file missing.")
    except Exception as e:
        print(f"❌ Audio playback crashed: {e}")

    print_header("4. Speech-to-Text (STT)")
    if os.path.exists(LAST_AUDIO):
        print("\n[A] Executing OFFLINE Transcription (PocketSphinx) on last recording...")
        start = time.time()
        try:
            offline_text = audio_utils.quick_stt(LAST_AUDIO)
            print(f"    RESULT: '{offline_text}' (took {time.time() - start:.2f}s)")
        except Exception as e:
            print(f"    ❌ Offline STT crashed: {e}")

        if online:
            print("\n[B] Executing ONLINE Transcription (Google/Groq)...")
            start = time.time()
            try:
                online_text = audio_utils.online_stt(LAST_AUDIO)
                print(f"    RESULT: '{online_text}' (took {time.time() - start:.2f}s)")
            except Exception as e:
                print(f"    ❌ Online STT crashed: {e}")
    else:
        print(f"⚠️ No cached audio found at {LAST_AUDIO}. Speak to the assistant normally once to cache a file for STT testing.")

    print_header("5. Offline Edge ML Intent Router")
    test_phrases = [
        "Play the song shape of you",
        "Wake me up at 7am",
        "Tell me a joke",
        "Remind me to buy groceries",
        "Connect bluetooth",
        "Test connection",
        "What time is it"
    ]
    
    for phrase in test_phrases:
        print(f"\nUser Input: '{phrase}'")
        cmd = match_offline_command(phrase)
        if cmd:
            print(f"  ✅ Edge Classification: [{cmd}]")
            resp = process_offline_command(cmd, phrase)
            print(f"  👉 System Action Executed: -> {resp}")
        else:
            print(f"  ❌ Edge Classification Failed (Would fallback to cloud)")

    if online:
        print_header("6. Gemini API Routing (Online)")
        print("Querying Gemini API directly simulating cloud logic...")
        try:
            gemini_resp = classify_intent("Who is the president?", api_key=GEMINI_API_KEY, backup_key=GEMINI_API_KEY_BACKUP)
            print("✅ Gemini Raw JSON Response Received.")
        except Exception as e:
            print(f"❌ Gemini API Error: {e}")

    print("\n" + "=" * 60)
    print("✅ AUTOMATED SUITE COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    try:
        run_all_tests()
    except KeyboardInterrupt:
        print("\nExiting Automated Suite.")
