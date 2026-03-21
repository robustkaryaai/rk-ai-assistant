"""
RK AI Pi client v3.0.0

Behavior summary:
1. Loop: ensure online/offline state.
2. Listen for wake word "rk" via PocketSphinx.
3. Record utterance, send to backend if online.
   - Delete audio once sent.
   - Parse backend reply, handle news/weather/music/announce.
4. If offline, use PocketSphinx for STT and run local commands.
5. Quick STT shortcut while online to catch media control intents.

Designed for Raspberry Pi. Uses SpeechRecognition (online) and PocketSphinx (offline).
"""

from __future__ import annotations

import os
import sys

# Allow running this script directly (python main.py) by setting up package context
if __name__ == "__main__" and __package__ is None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    sys.path.insert(0, parent_dir)
    __package__ = "rk_assistant"

import json
import subprocess
import tempfile
import threading
import time
import traceback as tb
from pathlib import Path
from typing import Optional

import requests

from . import audio_utils
from .audio_utils import (
    load_vosk_model,
    online_stt,
    play_audio_url,
    quick_stt,
    record_audio,
    record_until_silence,
    set_volume,
    stop_process,
    synthesize_to_wav,
    wait_for_wake_word,
)

# NOTE: Some deployments may have an older audio_utils.py missing live_stt_listen.
#       Keep the process alive by falling back to a no-op listener.
def _live_stt_stub(*_args, **_kwargs) -> str:
    return ""

live_stt_listen = getattr(audio_utils, "live_stt_listen", _live_stt_stub)
# Use new hybrid TTS (gTTS online, espeak offline)
from .audio_utils_simple import speak

from .config import (
    ERROR_LOG_FILE, 
    LAST_AUDIO, 
    WAKE_WORD, 
    WAKE_WORDS, 
    BACKEND_BASE_URL, 
    GEMINI_API_KEY, 
    GEMINI_API_KEY_BACKUP, 
    GEMINI_MODEL, 
    USE_GEMINI_DIRECT,
    SILENCE_TIMEOUT,
    PHRASE_TIME_LIMIT
)
from .audio_utils import setup_microphone_volume
from .networking import (
    generate_slug,
    is_online,
    post_audio_to_backend,
    post_text_to_backend,
    read_slug,
    write_slug,
    wait_for_internet,
    sync_wifi_from_appwrite,
    report_state,
)
from .offline_commands import match_offline_command, process_offline_command
from .weather_news import fetch_news, fetch_weather
from .intent_classifier import guess_fallback_intent, start_pending_request_msg
from .reset_monitor import start_reset_monitor, update_activity
from . import settings_sync
from . import music_manager
from . import command_poller
from . import schedule_manager
from . import local_handlers
from . import gemini_client
from . import self_diagnosis
from .error_monitor import register_error, get_monitor
from . import alarm_manager

# Global State
is_first_boot = False

import fcntl

def acquire_lock():
    """Ensure only one instance of the assistant is running."""
    lock_file = "/tmp/rk_assistant.lock"
    # Open or create the lock file
    f = open(lock_file, 'w')
    try:
        # Try to acquire an exclusive lock without blocking
        fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except IOError:
        print("[main] FATAL: Another instance of RK Assistant is already running. Exiting.")
        sys.exit(1)

def main():
    """Main entry point for the assistant."""
    # Acquire global process lock
    _lock_handle = acquire_lock()
    global is_first_boot
    
    print("\n" + "="*30)
    print("✓ Initializing RK AI Assistant...")
    print("="*30 + "\n")

    # 0. Basic Setup & Identity
    slug_val, _ = read_slug()
    if not slug_val:
        print("[main] No slug found! Using default 000000000", flush=True)
        slug_val = "000000000"

    is_first_boot = "--first-boot" in sys.argv

    # 1. Check internet connectivity immediately
    online = is_online()

    # 0.5 Start background managers
    print("[main] Starting background managers...", flush=True)
    
    def handle_backend_reply_sync(text: str):
        """Sync wrapper for handle_backend_reply used by background managers."""
        nonlocal online
        if not text: return
        # Create a mock music holder
        mock_holder = {"proc": None}
        handle_backend_reply(text, online, mock_holder, slug_val)

    alarm_manager.start_alarm_checker()
    schedule_manager.start_schedule_monitor(handle_backend_reply_sync)
    command_poller.start_command_poller(slug_val)
    start_reset_monitor()

    # Register voice callback for remote commands
    command_poller.register_voice_callback(handle_backend_reply_sync)
    
    # 2. Normal Startup Greeting
    if online:
        greeting = settings_sync.get_greeting_phrase()
        # Check for quiet flag file (from night update)
        quiet_flag = Path("/tmp/.quiet_startup")
        is_quiet = "--quiet" in sys.argv
        if quiet_flag.exists():
            print("[startup] Quiet mode active from night update.")
            quiet_flag.unlink()
            is_quiet = True

        if is_first_boot:
            print("[main] First boot detected.")
            speak(f"{greeting}! I have connected to the internet now let me setup my things")
            time.sleep(1)
            
            sound_path = str(Path(__file__).parent / "sounds" / "preparing.mp3")
            proc = play_audio_url(sound_path)
            if proc: proc.wait()
        elif not is_quiet:
            start_msg = f"{greeting}! RK AI assistant is starting up"
            print(f"[main] {start_msg}")
            speak(start_msg)
            time.sleep(1)
    
    # Initialize and Calibrate Microphone ONE TIME here
    recognizer = None
    mic = None
    if getattr(audio_utils, "SPEECH_RECOGNITION_AVAILABLE", False) and getattr(audio_utils, "sr", None) is not None:
        try:
            # FORCE HARDWARE GAIN FIRST
            setup_microphone_volume()
            
            print("[stt] Initializing microphone... (Supressing ALSA logs)", flush=True)
            
            # Suppress ALSA warnings during PyAudio init
            with audio_utils.no_alsa_err():
                recognizer = audio_utils.sr.Recognizer()
                recognizer.dynamic_energy_threshold = True  
                # User optimization: lower threshold for clean audio
                recognizer.energy_threshold = 300 # Sane default floor
            recognizer.pause_threshold = 1.2   # Wait longer for user to finish naturally
            recognizer.phrase_threshold = 0.3  # Only start if it's a real phrase
            recognizer.non_speaking_duration = 0.8 # Allow longer natural pauses between words
            
            from .config import MIC_DEVICE_INDEX, MIC_DEVICE_NAME
            device_idx = MIC_DEVICE_INDEX
            
            # Find clean_mic index if configured
            if MIC_DEVICE_NAME:
                print(f"[stt] Searching for microphone: {MIC_DEVICE_NAME}")
                try:
                    with audio_utils.no_alsa_err():
                        for i, name in enumerate(audio_utils.sr.Microphone.list_microphone_names()):
                            if MIC_DEVICE_NAME in name:
                                print(f"[stt] Found '{name}' at index {i}")
                                device_idx = i
                                break
                except Exception as e:
                    print(f"[stt] Error listing microphones: {e}")

            if device_idx is not None and device_idx < 0:
                device_idx = None
                
            print(f"[stt] Using Microphone Index: {device_idx}")
            
            with audio_utils.no_alsa_err():
                mic = audio_utils.sr.Microphone(device_index=device_idx)
            
            if mic is not None:
                print("[stt] Calibrating microphone for ambient noise (5 seconds)...", flush=True)
                try:
                    with audio_utils.no_alsa_err():
                        with mic as source:
                            # Shorter calibration for better UX
                            recognizer.adjust_for_ambient_noise(source, duration=5.0)
                            print(f"[stt] Done! Energy threshold set to: {recognizer.energy_threshold}")
                except Exception as e:
                    print(f"[stt] Calibration failed: {e}")
        except Exception as e:
            print(f"[stt] Error during microphone setup: {e}")

    # Voice command handler is now registered during manager startup

    music_proc_holder = {"proc": None}
    print("[main] RK AI is ready.", flush=True)

    # 3. MAIN LOOP
    while True:
        try:
            # 🚀 Check if device is muted before starting STT
            from .command_poller import get_mute_state
            if get_mute_state():
                print("[main] Device is MUTED. Skipping STT loop.", end="\r")
                report_state(slug_val, "muted")
                time.sleep(2)
                continue

            update_activity() # Signal we are alive to reset monitor
            online = is_online()
            
            # REPORT STATE PERIODICALLY
            report_state(slug_val, "idle")

            if online:
                # --- ONLINE MODE (PocketSphinx Wake Word + Google STT) ---
                detected = audio_utils.wait_for_wake_word(use_offline=False, recognizer=recognizer, mic=mic)
                
                if detected:
                    update_activity()
                    # User feedback
                    play_audio_file_local("listen.wav")
                    
                    print("[stt] Wake word detected. Listening...", flush=True)
                    
                    # 🚀 NEW: DIRECT LIVE STT (No file saving needed)
                    if recognizer and mic:
                        text = live_stt_listen(recognizer, mic, slug_val, timeout=10, phrase_time_limit=PHRASE_TIME_LIMIT)
                    else:
                        # Fallback to old recording method
                        audio_path = record_until_silence(silence_duration=SILENCE_TIMEOUT)
                        text = online_stt(audio_path) if audio_path else ""
                    
                    if text:
                        # 🚀 QUICK Media Control Shortcut
                        # If the text is very short and matches media commands, do it locally/instantly
                        offline_kw = match_offline_command(text.lower())
                        if offline_kw in ["stop", "pause", "resume", "volume up", "volume down", "mute", "unmute"]:
                            print(f"[main] Quick command detected: {offline_kw}")
                            resp = process_offline_command(offline_kw, text, music_proc_holder.get("proc"))
                            if resp: speak(resp)
                            continue

                        # Standard Gemini/Backend Path
                        handle_backend_reply(text, online, music_proc_holder, slug_val)
                    else:
                        print("[stt] Nothing heard.")

            elif not online:
                # --- OFFLINE MODE (PocketSphinx) ---
                print("\n[stt] 📡 Running in OFFLINE mode.", flush=True)
                detected = audio_utils.wait_for_wake_word(use_offline=True, recognizer=recognizer, mic=mic)
                
                if detected:
                    update_activity()
                    print("[stt] Wake word detected. Recording command...", flush=True)
                    audio_path = audio_utils.record_audio(recognizer=recognizer, mic=mic)
                    
                    if audio_path:
                        text = audio_utils.quick_stt(str(audio_path))
                        if text:
                            text_lower = text.lower()
                            print(f"[stt] Heard offline: '{text_lower}'")
                            offline_kw = match_offline_command(text_lower)
                            
                            if offline_kw:
                                resp = process_offline_command(offline_kw, text, music_proc_holder.get("proc"))
                                
                                if str(resp).startswith("_PLAY_MUSIC_|"):
                                     query = resp.split("|", 1)[1]
                                     proc = music_manager.play_music(query)
                                     if proc: music_proc_holder["proc"] = proc
                                elif resp == "_RK_UPDATE_":
                                     speak("Checking for updates and restarting.")
                                     subprocess.run(["git", "pull", "origin", "main"], cwd=str(BASE_DIR.parent))
                                     subprocess.run(["sudo", "systemctl", "restart", "rk-assistant.service"])
                                     return
                                elif resp == "_RK_SHUTDOWN_":
                                     speak("Shutting down the system.")
                                     subprocess.run(["sudo", "shutdown", "-h", "now"])
                                     return
                                elif resp == "_RK_REBOOT_":
                                     speak("Rebooting the system.")
                                     subprocess.run(["sudo", "reboot"])
                                     return
                                     
                                if resp == "_PLAY_AGAIN_":
                                    query = music_manager.last_played_query
                                    if query:
                                        trigger_music_playback(query, music_proc_holder)
                                elif resp:
                                    speak(resp)
                            else:
                                print("[stt] No specific offline intent matched.")
                        else:
                             print("[stt] PocketSphinx transcribed nothing.")
                    else:
                        print("[stt] Nothing recorded (silence).")

        except Exception as e:
            print(f"[main] Error in main loop: {e}")
            tb.print_exc()
            time.sleep(5)

def play_audio_file_local(filename):
    """Helper to play sounds from the assets folder."""
    p = Path(__file__).parent / "assets" / filename
    if p.exists():
        audio_utils.play_audio_file(str(p))

def trigger_music_playback(query, music_proc_holder):
    """Start music playback in a way that doesn't block the main loop."""
    # Stop existing
    if music_proc_holder.get("proc"):
        stop_process(music_proc_holder["proc"])
    
    # Start new
    proc = music_manager.play_music(query)
    if proc:
        music_proc_holder["proc"] = proc

def handle_backend_reply(text, online, music_proc_holder, slug):
    """Process text via Gemini or Backend and handle the response actions."""
    print(f"[gemini] Processing: '{text}'")
    
    # 1. Try Direct Gemini First (Fastest)
    reply_text = ""
    if USE_GEMINI_DIRECT and GEMINI_API_KEY:
        try:
            # Fix: call_gemini_direct doesn't exist, use get_conversational_response
            reply_text = gemini_client.get_conversational_response(text, api_key=GEMINI_API_KEY)
        except Exception as e:
            print(f"[gemini] Direct error: {e}")

    # 2. Fallback to Backend
    if not reply_text:
        # Fix: missing slug argument, and handle dict return
        resp = post_text_to_backend(text, slug)
        if isinstance(resp, dict):
            reply_text = resp.get("reply", "")
        else:
            reply_text = str(resp)

    if not reply_text:
        speak("I am having trouble connecting to my brain.")
        return

    print(f"[gemini] Reply: {reply_text}")
    
    # 3. Parse Intent (Music, News, Weather, Alarms, RexyCore Desktop)
    # Fix: guess_fallback_intent returns a list of intent objects
    intents = gemini_client.classify_intent(text, api_key=GEMINI_API_KEY)
    
    for intent_obj in intents:
        intent = intent_obj.get("intent", "general")
        params = intent_obj.get("parameters", {})
        
        if intent == "music":
            query = reply_text.replace("Searching for", "").replace("Playing", "").strip()
            trigger_music_playback(query, music_proc_holder)
            speak(reply_text)
        elif intent == "weather":
            speak(reply_text)
        elif intent == "news":
            speak(reply_text)
        elif intent in ["cozy_setup", "focus_mode", "open_app"]:
            from .desktop_link import trigger_desktop_action
            speak(reply_text)
            trigger_desktop_action(intent, params, slug=slug)
        elif intent == "alarm":
            speak(reply_text)
        else:
            # Standard Conversational Reply
            speak(reply_text)

if __name__ == "__main__":
    slug_val = "000000000"
    try:
        from .networking import read_slug
        slug_val, _ = read_slug()
    except:
        pass

    try:
        main()
    except KeyboardInterrupt:
        print("\n[main] Exiting by user request.")
        sys.exit(0)
    except Exception as e:
        error_msg = str(e)
        traceback_str = tb.format_exc()
        print(f"\n[main] FATAL ERROR: {error_msg}")
        print(traceback_str)
        
        # 🚀 TRIGGER SELF-DIAGNOSIS
        try:
            from .self_diagnosis import run_immediate_diagnosis
            run_immediate_diagnosis(
                slug=slug_val or "000000000",
                error_type=type(e).__name__,
                message=error_msg,
                traceback_str=traceback_str
            )
        except Exception as diag_e:
            print(f"[main] Self-diagnosis failed to start: {diag_e}")
            
        sys.exit(1)
