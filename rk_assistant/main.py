"""
RK AI Pi client.

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
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

import requests

from . import audio_utils
from .audio_utils import (
    live_stt_listen,
    load_pocketsphinx_decoder,
    online_stt,
    play_audio_url,
    quick_stt,
    record_audio,
    record_until_silence,
    set_volume,
    speak,
    stop_process,
    synthesize_to_wav,
    wait_for_wake_word,
)
from .config import ERROR_LOG_FILE, LAST_AUDIO, WAKE_WORD, WAKE_WORDS, BACKEND_BASE_URL, GEMINI_API_KEY, GEMINI_API_KEY_BACKUP, GEMINI_MODEL, USE_GEMINI_DIRECT
from .networking import (
    generate_slug,
    is_online,
    post_audio_to_backend,
    post_text_to_backend,
    read_slug,
    write_slug,
    setup_bluetooth,
    wait_for_internet,
)
from .offline_commands import handle_offline_command, match_offline_command, offline_ai_reply
from .weather_news import fetch_news, fetch_weather
from .provisioning_service import start_ble_service
from .intent_classifier import guess_fallback_intent, start_pending_request_msg, needs_backend
from . import gemini_client
from . import local_handlers



def _speak_twice(text: str) -> None:
    if not text:
        return
    speak(text)
    time.sleep(0.2)
    speak(text)


def _log_backend_error(error_msg: str, exception: Optional[Exception] = None) -> None:
    """Log backend errors to backend_error_log.txt."""
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {error_msg}"
        if exception:
            log_entry += f"\nException: {str(exception)}"
        log_entry += "\n" + "-" * 50 + "\n"
        with open(ERROR_LOG_FILE, "a") as f:
            f.write(log_entry)
    except Exception:
        pass  # Silently fail if logging fails

def _send_to_backend_async(text: str, slug: str) -> None:
    """Send request to backend asynchronously (fire and forget)."""
    def _async_send():
        try:
            print(f"[backend-async] Sending request to backend: '{text}'", flush=True)
            post_text_to_backend(text, slug)
            print(f"[backend-async] Request sent successfully", flush=True)
        except Exception as e:
            print(f"[backend-async] Error: {e}", flush=True)
            _log_backend_error("Async backend request failed", e)
    
    # Start in background thread
    thread = threading.Thread(target=_async_send, daemon=True)
    thread.start()


def ensure_valid_slug() -> Optional[str]:
    """Get or create slug, using backend ensure endpoint."""
    slug, verified = read_slug()
    
    if slug and verified:
        print(f"[slug] Locally verified slug: {slug}")
        return slug

    if not slug:
        slug = generate_slug()
        # New slugs are not verified yet
        write_slug(slug, verified=False)
        print(f"[slug] Generated new slug: {slug}")
    
    # Use backend ensure endpoint (auto-creates if needed)
    # Note: Render free tier has cold starts, can take 30-60s on first request
    try:
        url = f"{BACKEND_BASE_URL}/device/ensure/{slug}"
        print(f"[slug] Ensuring device exists: {url}", flush=True)
        print(f"[slug] This may take up to 60s if backend is sleeping...", flush=True)
        
        resp = requests.post(url, timeout=60)  # Long timeout for Render cold start
        
        if resp.ok:
            data = resp.json()
            if data.get("created"):
                print(f"[slug] ✓ Device created in backend for slug: {slug}")
            else:
                print(f"[slug] ✓ Device already exists for slug: {slug}")
            
            # Update local file to mark as verified
            write_slug(slug, verified=True)
            print(f"[slug] Marked slug as verified locally.")
            return slug
        else:
            print(f"[slug] Backend ensure failed: HTTP {resp.status_code}", file=sys.stderr)
            print(f"[slug] Continuing anyway with slug: {slug}")
            return slug  # Continue anyway
    except requests.exceptions.Timeout:
        print(f"[slug] Backend ensure timed out (60s), continuing with slug: {slug}", file=sys.stderr)
        return slug
    except Exception as e:
        print(f"[slug] Could not ensure device: {e}", file=sys.stderr)
        print(f"[slug] Continuing with slug: {slug}")
        return slug


def _monitor_music_for_wake(decoder_available: bool, music_proc_holder: dict) -> None:
    """Listen for wake word during playback; if heard, lower volume to hear user."""
    if not decoder_available:
        return
    proc = music_proc_holder.get("proc")
    if proc is None or proc.poll() is not None:
        return
    if wait_for_wake_word(decoder_available, WAKE_WORD, max_seconds=8):
        set_volume(-10)
        speak("Listening.")


def handle_backend_reply(reply_obj: dict, music_proc_holder: dict, decoder_available: bool = False, original_text: str = "") -> None:
    """Interpret backend JSON. Handles intent-based responses with proper intent checking."""
    # Validate JSON structure
    if not isinstance(reply_obj, dict):
        print(f"[backend] Invalid response type: {type(reply_obj)}")
        speak("Received invalid response from server.")
        return
    
    # Extract fields
    reply_text = (reply_obj.get("reply") or "").strip()
    song_url = reply_obj.get("song_url") or reply_obj.get("link")
    intent = (reply_obj.get("intent") or "").lower()
    
    # Check if response has intent field
    has_intent = "intent" in reply_obj
    
    print(f"[backend] Reply - Intent: {intent}, Has Reply: {bool(reply_text)}, Has Link: {bool(song_url)}")
    
    # Handle no response case
    if not reply_text and not song_url and not has_intent:
        # Check for fallback intent from local classifier
        fallback = guess_fallback_intent(original_text)
        if fallback:
            intent_type = fallback.get("intent")
            msg = start_pending_request_msg(intent_type)
            speak(msg)
            return
        speak("No response from server.")
        return
    
    # ===== INTENT-BASED HANDLING =====
    
    # ANNOUNCEMENT INTENT - Speak twice
    if has_intent and intent == "announcement":
        if reply_text:
            print(f"[intent] Announcement: {reply_text}")
            _speak_twice(reply_text)
        else:
            speak("Announcement received but no message provided.")
        return
    
    # MUSIC INTENT - Check for link and play
    if has_intent and intent == "music":
        if song_url:
            print(f"[intent] Music: {song_url}")
            if reply_text:
                speak(reply_text)
            stop_process(music_proc_holder.get("proc"))
            music_proc_holder["proc"] = play_audio_url(song_url)
            # Monitor for wake word during playback
            threading.Thread(target=_monitor_music_for_wake, args=(decoder_available, music_proc_holder), daemon=True).start()
        else:
            # Music intent but no link provided
            speak(reply_text or "Could not find the music.")
        return
    
    # ALARM INTENT - Check for time or ask
    if has_intent and intent == "alarm":
        alarm_time = reply_obj.get("time")
        if alarm_time:
            # Backend provided time, set alarm
            from .alarm_manager import set_alarm
            if set_alarm(alarm_time):
                speak(f"Alarm set for {alarm_time}.")
            else:
                speak("Could not set alarm. Invalid time format.")
        else:
            # No time provided, ask user
            from .alarm_manager import prompt_for_alarm_time, set_alarm
            time_str = prompt_for_alarm_time()
            if time_str and set_alarm(time_str):
                speak(f"Alarm set for {time_str}.")
            else:
                speak("Could not set alarm.")
        return
    
    # ===== LEGACY HANDLING (no intent field or other intents) =====
    
    lower = reply_text.lower() if reply_text else ""
    
    # Weather/news handling
    if "weather" in lower:
        weather = fetch_weather()
        if weather:
            current = weather.get("current", {})
            temp = current.get("temp_c")
            desc = current.get("condition", {}).get("text", "")
            speak(f"Weather {desc}, {temp} degrees Celsius.")
    if "news" in lower or "headline" in lower:
        news = fetch_news()
        if news and news.get("articles"):
            titles = [a.get("title", "") for a in news["articles"][:3]]
            speak("Top headlines. " + ". ".join(titles))
    
    # Speak the reply text
    if reply_text:
        if "announce" in lower:
            _speak_twice(reply_text)
        else:
            speak(reply_text)
    
    # Play music if URL provided (legacy support)
    if song_url and not has_intent:
        stop_process(music_proc_holder.get("proc"))
        music_proc_holder["proc"] = play_audio_url(song_url)
        threading.Thread(target=_monitor_music_for_wake, args=(decoder_available, music_proc_holder), daemon=True).start()


def _send_to_backend_async(text: str, slug: str):
    """Fire-and-forget sending text to backend."""
    def _send():
        post_text_to_backend(text, slug)
    threading.Thread(target=_send, daemon=True).start()


def process_online_command(text: str, slug: str, music_proc_holder: dict) -> None:
    """Helper to process a command string using Gemini/Backend."""
    if not text:
        return
        
    low = text.lower()
    
    # Local quick commands
    if "pause" in low and "music" in low:
        stop_process(music_proc_holder.get("proc"))
        speak("Paused.")
        return
    elif "volume up" in low:
        set_volume(+10)
        speak("Volume up.")
        return
    elif "volume down" in low:
        set_volume(-10)
        speak("Volume down.")
        return

    # Routing
    if USE_GEMINI_DIRECT and GEMINI_API_KEY:
        try:
            intents = gemini_client.classify_intent(text, api_key=GEMINI_API_KEY, backup_key=GEMINI_API_KEY_BACKUP, model_name=GEMINI_MODEL)
            local_intents = ["music", "alarm", "announcement", "chat", "general", "stop_alarm", "emergency_alarm", "fire_alarm"]
            backend_intents = ["image", "video", "docx", "ppt", "note", "planner", "timetable", "task", "lesson_plan", "exam_paper", "grading_sheet", "class_planner", "teacher_note"]
            
            if intents and len(intents) > 0:
                first_intent = intents[0]
                intent_name = first_intent.get("intent", "general")
                parameters = first_intent.get("parameters", {})
                
                if intent_name in local_intents:
                    response = local_handlers.handle_intent(intent_name, parameters, original_text=text)
                    if intent_name == "announcement":
                        _speak_twice(response.get("reply", ""))
                    elif response.get("reply"):
                        speak(response["reply"])
                elif intent_name in backend_intents:
                    speak("Working on it...")
                    _send_to_backend_async(text, slug)
                else:
                    _send_to_backend_async(text, slug)
            else:
                _send_to_backend_async(text, slug)
        except Exception:
            _send_to_backend_async(text, slug)
    else:
        _send_to_backend_async(text, slug)


def voice_flow(decoder_available: bool, music_proc_holder: dict, slug: str, recognizer=None, mic=None) -> None:
    """
    Unified voice flow.
    ONLINE: Uses Google STT continuously to listen. If 'rk' is in text, executes command.
    OFFLINE: Falls back to PocketSphinx for wake word.
    """
    # 1. Determine mode
    online = is_online()
    
    if online and recognizer and mic:
        # --- ONLINE MODE (Always-on Google STT) ---
        print(f"[wake] Listening (Google STT)... Say '{WAKE_WORD}'...", flush=True)
        
        # This blocks until a phrase is heard and transcribed
        # We increase phrase limit to allow natural speaking "rk play music"
        text = live_stt_listen(recognizer, mic, timeout=None, phrase_time_limit=10.0)
        
        if not text:
            return

        text_lower = text.lower()
        print(f"[stt] Heard: '{text}'")

        # Check for wake word
        if WAKE_WORD in text_lower:
            print(f"[wake] Wake word '{WAKE_WORD}' detected in online stream!")
            
            # Duck volume (visual/audio feedback)
            if music_proc_holder.get("proc"):
                set_volume(20)

            # Play wake sound
            play_audio_url("https://github.com/Starttoaster/rk-voice/raw/main/wake.wav")
            
            # Strip key word to get command
            # Find detection index
            idx = text_lower.find(WAKE_WORD)
            # Take everything AFTER the wake word
            command_part = text[idx + len(WAKE_WORD):].strip()
            
            # If user just said "rk", listen for follow-up
            if not command_part:
                print("[stt] Wake word heard but no command. Listening for follow-up...")
                command_part = live_stt_listen(recognizer, mic, timeout=5.0)
            
            if command_part:
                print(f"[stt] Processing command: '{command_part}'")
                
                # Execute logic
                if match_offline_command(command_part):
                     # Offline command (lights etc)
                     handle_offline_command(command_part, slug)
                     speak(offline_ai_reply(command_part))
                else:
                     # Online AI
                     process_online_command(command_part, slug, music_proc_holder)
                
                # Restore volume
                if music_proc_holder.get("proc"):
                    set_volume(80)
            else:
                print("[stt] No command heard after wake word.")
                if music_proc_holder.get("proc"):
                    set_volume(80)
            
        else:
            # print(f"[stt] Ignored (no wake word): {text}")
            pass
            
    else:
        # --- OFFLINE MODE (PocketSphinx Fallback) ---
        print(f"[wake] Waiting for wake word '{WAKE_WORD}' (Offline/Pocketsphinx)...", flush=True)
        woke = wait_for_wake_word(decoder_available, WAKE_WORDS)
        if not woke:
            return

        print("[wake] Wake word detected (Offline)!")
        
        if music_proc_holder.get("proc"):
            set_volume(20)
            
        play_audio_url("https://github.com/Starttoaster/rk-voice/raw/main/wake.wav")
        
        # Record & Transcribe
        audio_path = record_until_silence(LAST_AUDIO)
        
        text = ""
        # If we coincidentally have net now (flaky connection)
        if is_online():
             text = online_stt(audio_path)
        
        if not text:
             print("[stt] No transcription.")
             if music_proc_holder.get("proc"):
                set_volume(80)
             return
             
        print(f"[stt] Transcription: {text}")
        
        if match_offline_command(text):
            handle_offline_command(text, slug)
            speak(offline_ai_reply(text))
        else:
            if is_online():
                process_online_command(text, slug, music_proc_holder)
            else:
                speak("I am offline.")

        if music_proc_holder.get("proc"):
            set_volume(80)





def main():
    """Main entry point - asks for mode selection."""
    print("\n" + "="*30)
    print("Initializing RK AI Assistant...")
    print("="*30)
    
    # 1. Initialize Bluetooth (Speaker) FIRST
    setup_bluetooth()
    
    # 2. WAIT FOR INTERNET (User requested 2m max)
    wait_for_internet(max_minutes=2.0)
    
    # 3. SET INITIAL VOLUME (ensure we can hear it)
    set_volume(80) 

    # 4. INITIAL SPEECH
    start_msg = "Radhe Radhe RK AI assistant is starting up"
    print(f"[main] {start_msg}")
    speak(start_msg)
    time.sleep(1) # Give it a second

    # Initialize and Calibrate Microphone ONE TIME here
    recognizer = None
    mic = None
    if getattr(audio_utils, "SPEECH_RECOGNITION_AVAILABLE", False) and getattr(audio_utils, "sr", None) is not None:
        try:
            print("[stt] Initializing microphone...", flush=True)
            recognizer = audio_utils.sr.Recognizer()
            recognizer.dynamic_energy_threshold = False  # Use fixed threshold
            recognizer.energy_threshold = 150  # VERY sensitive
            recognizer.pause_threshold = 1.2   # Wait longer before ending
            recognizer.phrase_threshold = 0.05 # Start INSTANTLY
            recognizer.non_speaking_duration = 0.5  # Long pre-buffer to catch "rk"
            
            from .config import MIC_DEVICE_INDEX, MIC_SAMPLE_RATE
            mic = audio_utils.sr.Microphone(device_index=(None if MIC_DEVICE_INDEX < 0 else MIC_DEVICE_INDEX), sample_rate=MIC_SAMPLE_RATE)
            
            if mic is not None:
                print("[stt] Calibrating microphone for ambient noise (2 seconds)...", flush=True)
                try:
                    with mic as source:
                        recognizer.adjust_for_ambient_noise(source, duration=0.5)
                        print(f"[stt] Energy threshold set to: {recognizer.energy_threshold}", flush=True)
                except AttributeError as e:
                     if "'NoneType' object has no attribute 'close'" in str(e):
                         print("[stt] Warning: Microphone close error during calibration (ignored).", flush=True)
                     else:
                         raise e
                except Exception as e:
                     print(f"[stt] Warning: Ambient calibration failed: {e}", flush=True)

        except Exception as e:
            print(f"[stt] Failed to initialize microphone: {e}", flush=True)

    
    slug = ensure_valid_slug()
    if not slug:
        print("Missing or invalid slug.txt (must contain 9-digit code).", file=sys.stderr)
        return
    
    ready_msg = "Radhe Radhe RK AI assistant is ready"
    print(f"\n{ready_msg}")
    speak(ready_msg)

    print("\n" + "="*60)
    print("RK AI ASSISTANT STARTUP")
    print(f"Device Slug: {slug}")
    print("="*60)
    
    # Start BLE Provisioning Service (Daemon Thread)
    try:
        ble_thread = threading.Thread(target=start_ble_service, args=(slug,), daemon=True)
        ble_thread.start()
        print(f"[ble] Provisioning service started for {slug}")
    except Exception as e:
        print(f"[ble] Failed to start service: {e}", file=sys.stderr)

    # Default to Voice Mode
    print("\n" + "="*30)
    print("STARTING VOICE MODE")
    print("="*30 + "\n")
    
    decoder_available = load_pocketsphinx_decoder()
    music_proc_holder = {"proc": None}

    # Voice mode: standard wake word loop
    while True:
        try:
            voice_flow(decoder_available, music_proc_holder, slug, recognizer=recognizer, mic=mic)
            time.sleep(0.5) # Throttle loop
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[main] Error in voice loop: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
