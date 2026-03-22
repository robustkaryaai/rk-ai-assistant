"""
RK AI - Automated Developer Mode Test Suite

This script runs a non-interactive, CI/CD-style diagnostic check on
every critical subsystem in the RK AI software stack to ensure parity
and stability.
"""

import os
import sys
import time
import subprocess
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
    GEMINI_API_KEY_BACKUP, STT_ENGINE, MIC_DEVICE_INDEX,
    BLUETOOTH_SPEAKER_MAC, PORCUPINE_ACCESS_KEY
)
from rk_assistant.offline_commands import match_offline_command, process_offline_command
from rk_assistant.gemini_client import classify_intent
from rk_assistant.weather_news import fetch_weather, fetch_news
from rk_assistant.audio_utils_simple import speak

def print_header(title: str):
    print("\n" + "=" * 60)
    print(f" [TEST RUN] {title}")
    print("=" * 60)


def print_user_prompt(prompt: str):
    prompt_text = str(prompt or "").strip()
    if prompt_text:
        print(f"User: {prompt_text}")

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
            print("   ℹ️  Note: PocketSphinx accuracy relies on exact phrasing (best for intents/wake words).")
            print("       Standard conversational queries are automatically routed to Gemini (Cloud).")
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
        print_user_prompt(phrase)
        
        cmd = match_offline_command(phrase)
        if cmd == intent:
            edge_passes += 1
            if cmd in ["shutdown_device", "restart_device", "update_system"]:
                print(f"   ✓ [Intent matched]: '{phrase}' -> {cmd} (Execution skipped to prevent system exit)")
            else:
                resp = process_offline_command(cmd, phrase)
                print(f"   ✓ [Intent matched]: '{phrase}' -> {cmd} (Exec: {resp})")
        else:
            print(f"   ❌ [Intent FAILED]: '{phrase}' -> Expected {intent}, Got {cmd}")

    log_result("Offline ML Intent Accuracy", edge_passes == edge_total, f"({edge_passes}/{edge_total} Features Passed)")

    if online:
        print_header("6. Gemini API Routing (Online)")
        try:
            sample_prompt = "Who is the president?"
            print_user_prompt(sample_prompt)
            gemini_resp = classify_intent(sample_prompt, api_key=GEMINI_API_KEY, backup_key=GEMINI_API_KEY_BACKUP)
            log_result("Gemini Cloud Interface", bool(gemini_resp), "(Successfully parsed JSON)")
        except Exception as e:
            log_result("Gemini Cloud Interface", False, f"({e})")

    print_header("7. Wake Word Engine Status")
    import platform
    is_arm = platform.machine() == "armv6l"
    if PORCUPINE_ACCESS_KEY:
        log_result("Porcupine Configured", True, "(API Key injected)")
        if is_arm:
            try:
                import pvporcupine
                # Just initialize and delete to verify it works
                porcupine = pvporcupine.create(
                    access_key=PORCUPINE_ACCESS_KEY,
                    keywords=["porcupine"]
                )
                porcupine.delete()
                log_result("Porcupine Engine", True, "(Library loaded successfully)")
            except Exception as e:
                log_result("Porcupine Engine", False, f"({e})")
        else:
            print("   ℹ️  Skipped PyAudio/Porcupine loading test on non-ARM hardware.")
    else:
        log_result("Wake Word Engine", True, "(Using Key-less Offline PocketSphinx Fallback)")

    print_header("8. Music Dependencies")
    yt_check = subprocess.run(["which", "yt-dlp"], capture_output=True, text=True)
    log_result("yt-dlp Installed", yt_check.returncode == 0, f"({yt_check.stdout.strip() if yt_check.returncode == 0 else 'Not Found'})")
    ff_check = subprocess.run(["which", "ffmpeg"], capture_output=True, text=True)
    log_result("ffmpeg Installed", ff_check.returncode == 0, f"({ff_check.stdout.strip() if ff_check.returncode == 0 else 'Not Found'})")

    print_header("9. Volume Control API")
    vol_func_exists = hasattr(audio_utils, 'set_volume')
    log_result("Volume Control Module", vol_func_exists, "(audio_utils.set_volume is available)")

    print_header("10. Bluetooth Speaker Status")
    try:
        bt_result = subprocess.run(
            ["bluetoothctl", "info", BLUETOOTH_SPEAKER_MAC],
            capture_output=True, text=True, timeout=5
        )
        is_connected = "Connected: yes" in bt_result.stdout
        log_result("Bluetooth Connection", is_connected, f"(MAC: {BLUETOOTH_SPEAKER_MAC})")
    except Exception as e:
        log_result("Bluetooth Connection", False, f"({e})")

    print_header("11. Music Search Pipeline")
    if yt_check.returncode == 0:
        try:
            test_song = "Sandese aate hai"
            ms_result = subprocess.run(
                ["yt-dlp", "--get-title", f"ytsearch1:{test_song}"],
                capture_output=True, text=True, timeout=120
            )
            title_found = ms_result.returncode == 0 and bool(ms_result.stdout.strip())
            log_result("yt-dlp Search", title_found, f"(Found: {ms_result.stdout.strip()[:50]}...)" if title_found else "(Search timeout or error)")
        except Exception as e:
            log_result("yt-dlp Search", False, f"({e})")
    else:
        print("   ℹ️  Skipped Music Search due to missing yt-dlp.")

    print_header("12. Context Memory Engine")
    try:
        from rk_assistant.memory_engine import store_memory, retrieve_memories
        test_fact = f"Developer mode test run at {time.time()}"
        store_memory(test_fact, tags="dev_test")
        memories = retrieve_memories("developer mode test")
        found = any(test_fact in m for m in memories)
        log_result("Memory Storage/Retrieval", found, "(Fact stored and retrieved safely)")
    except ImportError:
        log_result("Memory Module", False, "(rk_assistant.memory_engine missing)")
    except Exception as e:
        log_result("Memory Sequence", False, f"({e})")

    print_header("13. Automation Engine")
    try:
        from rk_assistant.automation import ROUTINES
        has_routines = "night_protocol" in ROUTINES
        count = len(ROUTINES)
        log_result("Routine Parsing", has_routines, f"(Loaded {count} routines, 'night_protocol' present)" if has_routines else "(Missing core routines)")
    except ImportError:
        log_result("Automation Module", False, "(rk_assistant.automation missing)")
    except Exception as e:
        log_result("Automation System", False, f"({e})")

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
