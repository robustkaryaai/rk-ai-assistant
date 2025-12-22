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
from . audio_utils import (
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
from .config import ERROR_LOG_FILE, LAST_AUDIO, WAKE_WORD, BACKEND_BASE_URL
from .networking import (
    generate_slug,
    is_online,
    post_audio_to_backend,
    post_text_to_backend,
    read_slug,
    write_slug,
    setup_bluetooth,
)
from .offline_commands import handle_offline_command, match_offline_command, offline_ai_reply
from .weather_news import fetch_news, fetch_weather
from .provisioning_service import start_ble_service
from .intent_classifier import guess_fallback_intent, start_pending_request_msg


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


def offline_flow(decoder_available: bool, music_proc_holder: dict) -> None:
    text = quick_stt(decoder_available, seconds=4)
    cmd = match_offline_command(text)
    if cmd:
        handle_offline_command(cmd, music_proc_holder.get("proc"))
    else:
        speak(offline_ai_reply(text or ""))


def online_flow(decoder_available: bool, music_proc_holder: dict, slug: str) -> None:
    print("[online] Streaming Google STT...", flush=True)
    try:
        # Try live Google STT with error handling
        if getattr(audio_utils, "SPEECH_RECOGNITION_AVAILABLE", False) and getattr(audio_utils, "sr", None) is not None:
            recognizer = audio_utils.sr.Recognizer()
            recognizer.dynamic_energy_threshold = False  # Use fixed threshold
            recognizer.energy_threshold = 150  # VERY sensitive
            recognizer.pause_threshold = 1.2   # Wait longer before ending
            recognizer.phrase_threshold = 0.05 # Start INSTANTLY
            recognizer.non_speaking_duration = 0.5  # Long pre-buffer to catch "rk"
            
            mic = None
            try:
                from .config import MIC_DEVICE_INDEX, MIC_SAMPLE_RATE
                mic = audio_utils.sr.Microphone(device_index=(None if MIC_DEVICE_INDEX < 0 else MIC_DEVICE_INDEX), sample_rate=MIC_SAMPLE_RATE)
            except Exception as e:
                typ = type(e).__name__
                print(f"[stt] Microphone open failed ({typ}): {e}", flush=True)
                _log_backend_error(f"Microphone open failed: {typ}", e)
                return
            
            if mic is not None:
                print("[stt] Calibrating microphone for ambient noise (2 seconds)...", flush=True)
                try:
                    with mic as source:
                        # Longer calibration to properly measure background noise
                        recognizer.adjust_for_ambient_noise(source, duration=2.0)
                        print(f"[stt] Energy threshold set to: {recognizer.energy_threshold}", flush=True)
                except Exception as e:
                    typ = type(e).__name__
                    print(f"[stt] Ambient noise calibration failed ({typ}): {e}", flush=True)
                    _log_backend_error(f"Ambient noise calibration failed: {typ}", e)
                
                handled = {"done": False}
                def _cb(recognizer_cb, audio_cb):
                    try:
                        text = recognizer.recognize_google(audio_cb)
                        print(f"[online] Google STT: '{text}'", flush=True)
                        low = text.lower()
                        # Check for wake word variations (rk, aarti, arty, arctic, are key, etc.)
                        wake_words = ["rk", "aarti", "arty", "arctic", "are key", "artie", "r k", "arti"]
                        if not any(wake in low for wake in wake_words):
                            return
                        print("[online] ✓ Wake word detected in transcription!", flush=True)
                        if "pause" in low:
                            stop_process(music_proc_holder.get("proc"))
                            speak("Paused.")
                        elif "volume up" in low:
                            set_volume(+5)
                            speak("Volume up.")
                        elif "volume down" in low:
                            set_volume(-5)
                            speak("Volume down.")
                        else:
                            print(f"[online] Sending text to backend: '{text}'", flush=True)
                            try:
                                resp = post_text_to_backend(text, slug)
                                print(f"[online] Backend response: {resp}", flush=True)
                                handle_backend_reply(resp, music_proc_holder, decoder_available, original_text=text)
                            except Exception as be:
                                print(f"[backend] Error: {be}", flush=True)
                                _log_backend_error("Backend communication failed", be)
                                speak("Could not reach backend server.")
                        handled["done"] = True
                    except audio_utils.sr.UnknownValueError:
                        pass  # Normal - background noise, do nothing
                    except audio_utils.sr.RequestError as e:
                        print(f"[stt] Google STT request error: {e}", flush=True)
                        _log_backend_error("Google STT request failed", e)
                    except Exception as e:
                        typ = type(e).__name__
                        msg = str(e) or typ
                        print(f"[stt] Live STT error: {msg}", flush=True)
                        _log_backend_error(f"Live STT error: {typ}", e)
                
                try:
                    stop_fn = recognizer.listen_in_background(mic, _cb, phrase_time_limit=10)
                except Exception as e:
                    typ = type(e).__name__
                    print(f"[stt] listen_in_background failed ({typ}): {e}", flush=True)
                    _log_backend_error(f"listen_in_background failed: {typ}", e)
                    stop_fn = None
                    return
                
                # Keep monitoring for 60 seconds, then restart
                start = time.time()
                while not handled["done"] and (time.time() - start) < 60:
                    time.sleep(0.1)
                
                if stop_fn:
                    try:
                        stop_fn(wait_for_stop=False)
                    except Exception:
                        pass
                
                # If command was handled, return. Otherwise loop will continue monitoring
                if handled["done"]:
                    return
    
    except Exception as e:
        error_msg = f"Error in online flow: {str(e)}"
        print(f"[error] {error_msg}", file=sys.stderr, flush=True)
        _log_backend_error(error_msg, e)
        time.sleep(1)  # Brief pause before retry

def text_input_flow(slug: str) -> None:
    """TEMPORARY: Text input mode for testing without audio."""
    print("\n[text-mode] Enter your prompt (or 'quit' to exit):")
    text = input("> ").strip()
    
    if not text or text.lower() in ['quit', 'exit', 'q']:
        return
    
    print(f"[text-mode] You entered: '{text}'", flush=True)
    
    # Check if wake word "rk" is in the text
    if "rk" not in text.lower():
        print("[text-mode] Wake word 'rk' not detected, ignoring...", flush=True)
        return
    
    print("[text-mode] ✓ Wake word 'rk' detected!", flush=True)
    
    # Send TEXT to backend
    print(f"[text-mode] Sending text to backend...", flush=True)
    resp = post_text_to_backend(text, slug)
    
    # Handle backend response
    # Pass empty music_proc_holder since text mode doesn't need to stop music usually
    # But if music IS playing, we might want to stop it. Ideally we pass the real one.
    # For now, let's create a dummy one or use a shared one if we can refactor.
    # To keep it simple, we'll just handle the reply for speech.
    print(f"[text-mode] Backend response received.", flush=True)
    
    music_proc_holder = {"proc": None} # Placeholder for text mode
    handle_backend_reply(resp, music_proc_holder, decoder_available=False, original_text=text)


def main():
    """Main entry point - asks for mode selection."""
    print("\n" + "="*30)
    print("Initializing rk ai...")
    print("="*30)
    
    # Initialize Bluetooth (Speaker)
    setup_bluetooth()
    
    speak("Initializing rk ai")

    
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

    print("Select Mode:")
    print("1. Voice Mode (Wake word 'rk')")
    print("2. Text Mode (Type commands)")
    
    choice = input("\nEnter choice (1 or 2): ").strip()

    if choice == "2":
        print("\n" + "="*30)
        print("STARTING TEXT MODE")
        print("="*30 + "\n")
        while True:
            try:
                text_input_flow(slug)
            except KeyboardInterrupt:
                print("\n[text-mode] Exiting...")
                break
            except Exception as e:
                print(f"[text-mode] Error: {e}", flush=True)
        return

    # Default to Voice Mode
    print("\n" + "="*30)
    print("STARTING VOICE MODE")
    print("="*30 + "\n")
    
    decoder_available = load_pocketsphinx_decoder()
    music_proc_holder = {"proc": None}

    # Voice mode: standard wake word loop
    while True:
        online = is_online()
        _state = "online" if online else "offline"
        print(f"[state] {_state}", flush=True)

        if online:
            # Online mode: Google STT handles wake word detection inside online_flow
            online_flow(decoder_available, music_proc_holder, slug)
        else:
            # Offline mode: use PocketSphinx for wake word detection
            woke = wait_for_wake_word(decoder_available, WAKE_WORD)
            if not woke:
                time.sleep(1)
                continue
            offline_flow(decoder_available, music_proc_holder)

        # Small idle to avoid tight loop
        time.sleep(0.5)


if __name__ == "__main__":
    main()
