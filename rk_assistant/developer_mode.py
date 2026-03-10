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
    pass_count = 0
    total_count = 0
    
    def log_result(name: str, passed: bool, details: str = ""):
        nonlocal pass_count, total_count
        total_count += 1
        if passed:
            pass_count += 1
            print(f"✅ PASS | {name} {details}")
        else:
            print(f"❌ FAIL | {name} {details}")

    print_header("1. Core Network & Configuration")
    online = is_online()
    log_result("Internet Ping", online)
    
    slug, _ = read_slug()
    log_result("Device Slug Read", bool(slug), f"({slug})")
    
    print_header("2. Third Party API Integrations")
    if online:
        try:
            w = fetch_weather()
            log_result("Weather API", bool(w))
        except Exception as e:
            log_result("Weather API", False, f"({e})")
            
        try:
            n = fetch_news()
            log_result("News API", bool(n and len(n.get('articles', [])) > 0))
        except Exception as e:
            log_result("News API", False, f"({e})")
    else:
        print("Skipping API tests (Device is Offline).")
        
    print_header("3. Text-to-Speech (TTS) Engine Output")
    try:
        sound_path = str(Path(__file__).parent / "sounds" / "prepared.mp3")
        if os.path.exists(sound_path):
            audio_utils.play_audio_file(sound_path)
            log_result("Hardware Audio Synthesis", True)
        else:
            log_result("Hardware Audio Synthesis", False, "(Sound file missing)")
    except Exception as e:
        log_result("Hardware Audio Synthesis", False, f"({e})")

    print_header("4. Speech-to-Text (STT)")
    if os.path.exists(LAST_AUDIO):
        try:
            offline_text = audio_utils.quick_stt(LAST_AUDIO)
            log_result("Offline STT (PocketSphinx)", bool(offline_text), f"Heard: '{offline_text}'")
        except Exception as e:
            log_result("Offline STT (PocketSphinx)", False, f"({e})")

        if online:
            try:
                online_text = audio_utils.online_stt(LAST_AUDIO)
                log_result("Online STT (Cloud)", bool(online_text), f"Heard: '{online_text}'")
            except Exception as e:
                log_result("Online STT (Cloud)", False, f"({e})")
    else:
        print(f"⚠️ No cached audio found to text STT. Speak to the assistant to generate a cache file.")

    print_header("5. Offline Edge ML Intent Router")
    from rk_assistant.intent_classifier import TRAINING_DATA, MODEL_CACHE_PATH
    
    # Force retrain so we test the most recent code changes
    if os.path.exists(MODEL_CACHE_PATH):
        try:
            os.remove(MODEL_CACHE_PATH)
            print("🗑️ Wiped outdated Edge ML cache. Forcing immediate retraining...")
        except: pass
        
    print(f"Scanning {len(TRAINING_DATA)} distinct offline behaviors...")
    
    edge_passes = 0
    edge_total = len(TRAINING_DATA)
    
    for intent, phrases in TRAINING_DATA.items():
        if not phrases: continue
        phrase = phrases[0] # Test the primary trigger phrase for EVERY feature
        
        cmd = match_offline_command(phrase)
        if cmd == intent:
            edge_passes += 1
            # We don't want 21 lines of massive terminal spam, so we format tightly
            print(f"   ✓ [Intent matched]: '{phrase}' -> {cmd}")
        else:
            print(f"   ❌ [Intent FAILED]: '{phrase}' -> Expected {intent}, Got {cmd}")

    log_result("Offline ML Intent Accuracy", edge_passes == edge_total, f"({edge_passes}/{edge_total} Features Passed)")

    if online:
        print_header("6. Gemini API Routing (Online)")
        try:
            gemini_resp = classify_intent("Who is the president?", api_key=GEMINI_API_KEY, backup_key=GEMINI_API_KEY_BACKUP)
            log_result("Gemini Cloud Interface", bool(gemini_resp), "(Successfully parsed JSON)")
        except Exception as e:
            log_result("Gemini Cloud Interface", False, f"({e})")

    print_header("AUTOMATED DIAGNOSTICS SUMMARY")
    score = (pass_count / total_count) * 100 if total_count > 0 else 0
    print(f"Total Subsystems Tested: {total_count}")
    print(f"Subsystems Passed:       {pass_count}")
    print(f"System Health Score:     {score:.1f}%\n")
    
    if score == 100.0:
        print("✅ ALL SYSTEMS NOMINAL. RK AI is functionally healthy.")
    else:
        print("⚠️ HARDWARE DEGRADATION OR API FAILURE DETECTED. See logs above.")
        
    print("=" * 60)

if __name__ == "__main__":
    try:
        run_all_tests()
    except KeyboardInterrupt:
        print("\nExiting Automated Suite.")
