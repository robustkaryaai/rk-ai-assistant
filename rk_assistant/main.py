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


def handle_backend_reply(reply_obj: dict, music_proc_holder: dict, decoder_available: bool = False) -> None:
    """Interpret backend JSON. Handles intent-based responses matching buildTaskReply logic."""
    reply_text = (reply_obj.get("reply") or "").strip()
    song_url = reply_obj.get("song_url") or reply_obj.get("link")
    intent = (reply_obj.get("intent") or "").lower()
    
    # TEMPORARY RESTRICTION: Block PPT and Video generation
    if intent in ["ppt", "video"]:
        speak("Sorry, presentation and video generation are temporarily unavailable.")
        _log_backend_error(f"Blocked request for intent: {intent}")
        return

    if not reply_text and not song_url:
        speak("No response from server.")
        return

    lower = reply_text.lower()

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

    if reply_text:
        if intent == "announcement" or "announce" in lower:
            _speak_twice(reply_text)
        else:
            speak(reply_text)

    if song_url:
        stop_process(music_proc_holder.get("proc"))
        music_proc_holder["proc"] = play_audio_url(song_url)
        # run wake monitor in background
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
        if getattr(audio_utils, "SPEECH_RECOGNITION_AVAILABLE", False) and getattr(audio_utils, "sr", None) is not None:
            recognizer = audio_utils.sr.Recognizer()
            recognizer.dynamic_energy_threshold = True
            mic = None
            try:
                from .config import MIC_DEVICE_INDEX, MIC_SAMPLE_RATE
                mic = audio_utils.sr.Microphone(device_index=(None if MIC_DEVICE_INDEX < 0 else MIC_DEVICE_INDEX), sample_rate=MIC_SAMPLE_RATE)
            except Exception as e:
                typ = type(e).__name__
                print(f"[stt] Microphone open failed ({typ}): {e}", flush=True)
            if mic is not None:
                try:
                    with mic as source:
                        recognizer.adjust_for_ambient_noise(source, duration=0.5)
                except Exception as e:
                    typ = type(e).__name__
                    print(f"[stt] Ambient noise calibration failed ({typ}): {e}", flush=True)
                handled = {"done": False}
                def _cb(recognizer_cb, audio_cb):
                    try:
                        text = recognizer.recognize_google(audio_cb)
                        print(f"[online] Google STT: '{text}'", flush=True)
                        low = text.lower()
                        if "rk" not in low:
                            return
                        print("[online] ✓ Wake word 'rk' detected in transcription!", flush=True)
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
                            resp = post_text_to_backend(text, slug)
                            print(f"[online] Backend response: {resp}", flush=True)
                            handle_backend_reply(resp, music_proc_holder, decoder_available)
                        handled["done"] = True
                    except Exception as e:
                        typ = type(e).__name__
                        msg = str(e) or typ
                        print(f"[stt] Live STT error: {msg}", flush=True)
                try:
                    stop_fn = recognizer.listen_in_background(mic, _cb, phrase_time_limit=4)
                except Exception as e:
                    typ = type(e).__name__
                    print(f"[stt] listen_in_background failed ({typ}): {e}", flush=True)
                    stop_fn = None
                start = time.time()
                while not handled["done"] and (time.time() - start) < 15:
                    time.sleep(0.2)
                if stop_fn:
                    try:
                        stop_fn(wait_for_stop=False)
                    except Exception:
                        pass
                if handled["done"]:
                    return
        print("[online] Recording and using Google STT...", flush=True)
        audio_path = record_until_silence(LAST_AUDIO, silence_duration=2.0)
        print(f"[online] Audio recorded to {audio_path}", flush=True)
        print("[online] Transcribing with Google STT...", flush=True)
        transcription = online_stt(audio_path)
        if not transcription:
            try:
                audio_path.unlink(missing_ok=True)
            except Exception:
                pass
            return
        print(f"[online] Google STT result: '{transcription}'", flush=True)
        if "rk" not in transcription.lower():
            try:
                audio_path.unlink(missing_ok=True)
            except Exception:
                pass
            return
        print("[online] ✓ Wake word 'rk' detected in transcription!", flush=True)
        low = transcription.lower()
        if "pause" in low:
            stop_process(music_proc_holder.get("proc"))
            speak("Paused.")
            try:
                audio_path.unlink(missing_ok=True)
            except Exception:
                pass
            return
        if "volume up" in low:
            set_volume(+5)
            speak("Volume up.")
            try:
                audio_path.unlink(missing_ok=True)
            except Exception:
                pass
            return
        if "volume down" in low:
            set_volume(-5)
            speak("Volume down.")
            try:
                audio_path.unlink(missing_ok=True)
            except Exception:
                pass
            return
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass
        print(f"[online] Sending text to backend: '{transcription}'", flush=True)
        resp = post_text_to_backend(transcription, slug)
        print(f"[online] Backend response: {resp}", flush=True)
        handle_backend_reply(resp, music_proc_holder, decoder_available)
    except Exception as e:
        error_msg = f"Error in online flow: {str(e)}"
        print(f"[error] {error_msg}", file=sys.stderr, flush=True)
        _log_backend_error(error_msg, e)
        speak("Error processing voice input.")

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
    handle_backend_reply(resp, music_proc_holder, decoder_available=False)


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
