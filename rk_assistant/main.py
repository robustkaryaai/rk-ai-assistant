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
import traceback as tb
from pathlib import Path
from typing import Optional

import requests

from . import audio_utils
from .audio_utils import (
    load_pocketsphinx_decoder,
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

from .config import ERROR_LOG_FILE, LAST_AUDIO, WAKE_WORD, WAKE_WORDS, BACKEND_BASE_URL, GEMINI_API_KEY, GEMINI_API_KEY_BACKUP, GEMINI_MODEL, USE_GEMINI_DIRECT
from .networking import (
    generate_slug,
    is_online,
    post_audio_to_backend,
    post_text_to_backend,
    read_slug,
    write_slug,
    setup_microphone_volume,
    wait_for_internet,
)
from .offline_commands import handle_offline_command, match_offline_command, offline_ai_reply
from .weather_news import fetch_news, fetch_weather
from .provisioning_service import start_ble_service
from .intent_classifier import guess_fallback_intent, start_pending_request_msg, needs_backend
from . import gemini_client
from . import local_handlers
from . import settings_sync  # Sync mute/memory from Appwrite
from . import command_poller  # Poll and execute commands from mobile app
from .error_monitor import register_error, get_monitor
from . import self_diagnosis




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


def _send_to_backend_and_handle(text: str, slug: str, music_proc_holder: dict) -> None:
    """Send text to backend and handle the response (speak it)."""
    def _handler():
        try:
            print(f"[backend] Sending request: '{text}'...", flush=True)
            # This blocks this thread until response arrives (which is fine, it's a daemon thread)
            response = post_text_to_backend(text, slug)
            
            if response:
                print(f"[backend] Received response: {response}", flush=True)
                handle_backend_reply(response, music_proc_holder)
            else:
                print("[backend] Empty response received.")
                speak("I didn't get a response from the server.")
                
        except Exception as e:
            print(f"[backend] Error: {e}", flush=True)
            _log_backend_error("Backend request failed", e)
            speak("Sorry, I had trouble reaching the server.")

    # Start in background thread so we don't block the main listening loop completely
    # (Although user might want to block? usually better to keep listening for 'stop')
    threading.Thread(target=_handler, daemon=True).start()


def process_online_command(text: str, slug: str, music_proc_holder: dict) -> bool:
    """
    Helper to process a command string using Gemini/Backend.
    Returns: True if a follow-up is expected (conversational), False otherwise.
    """
    if not text:
        return False
        
    low = text.lower()
    
    # Local quick commands (instant, no acknowledgment needed)
    if "pause" in low and "music" in low:
        stop_process(music_proc_holder.get("proc"))
        speak("Paused.")
        return False
    elif "volume up" in low:
        set_volume(+10)
        speak("Volume up.")
        return False
    elif "volume down" in low:
        set_volume(-10)
        speak("Volume down.")
        return False

    # For complex commands, give immediate acknowledgment
    needs_backend_ack = False
    expect_followup = False
    
    # Routing
    if USE_GEMINI_DIRECT and GEMINI_API_KEY:
        try:
            intents = gemini_client.classify_intent(text, api_key=GEMINI_API_KEY, backup_key=GEMINI_API_KEY_BACKUP, model_name=GEMINI_MODEL)
            local_intents = ["music", "alarm", "announcement", "chat", "general", "stop_alarm", "emergency_alarm", "fire_alarm", "remember"]
            backend_intents = ["image", "video", "docx", "ppt", "note", "planner", "timetable", "task", "lesson_plan", "exam_paper", "grading_sheet", "class_planner", "teacher_note"]
            
            if intents and len(intents) > 0:
                first_intent = intents[0]
                intent_name = first_intent.get("intent", "general")
                parameters = first_intent.get("parameters", {})
                
                if intent_name in local_intents:
                    response = local_handlers.handle_intent(intent_name, parameters, original_text=text)
                    
                    # Special handling for local music
                    if response.get("intent") == "music_local":
                        speak(response.get("reply", "Playing music"))
                        query = response.get("query")
                        
                        from .music_manager import play_music
                        proc = play_music(query)
                        
                        if proc:
                            stop_process(music_proc_holder.get("proc"))
                            music_proc_holder["proc"] = proc
                            # Monitor for wake word while music plays
                            threading.Thread(target=_monitor_music_for_wake, args=(True, music_proc_holder), daemon=True).start()
                            return False # Music playing, don't follow up immediately
                        else:
                            speak("I couldn't find that song.")
                            return False
                            
                    elif intent_name == "announcement":
                        _speak_twice(response.get("reply", ""))
                        return False

                    elif response.get("reply"):
                        speak(response["reply"])
                        # If it's chat/general/remember, we EXPECT a follow-up
                        if intent_name in ["chat", "general", "remember"]:
                            return True
                        return False
                        
                elif intent_name in backend_intents:
                    # Immediate acknowledgment for backend requests
                    speak("Got it, let me get that answer for you.")
                    _send_to_backend_and_handle(text, slug, music_proc_holder)
                    return False
                else:
                    needs_backend_ack = True
                    _send_to_backend_and_handle(text, slug, music_proc_holder)
                    return False
            else:
                needs_backend_ack = True
                _send_to_backend_and_handle(text, slug, music_proc_holder)
                return False
        except Exception:
            needs_backend_ack = True
            _send_to_backend_and_handle(text, slug, music_proc_holder)
            return False
    else:
        needs_backend_ack = True
        _send_to_backend_and_handle(text, slug, music_proc_holder)
        return False
    
    # Acknowledge if sending to backend without specific intent
    if needs_backend_ack:
        speak("Got it, let me get that answer for you.")
    
    return False


def voice_flow(decoder_available: bool, music_proc_holder: dict, slug: str, recognizer=None, mic=None) -> None:
    """
    Unified voice flow.
    ONLINE: Uses Google STT continuously to listen. If 'rk' is in text, executes command.
    OFFLINE: Falls back to PocketSphinx for wake word.
    """
    # Check if device is muted (synced from Appwrite via mobile app)
    if settings_sync.is_device_muted():
        print("[voice] Device is muted, skipping listening...")
        time.sleep(2)  # Check again in 2 seconds
        return
    
    # 1. Determine mode
    online = is_online()
    
    if online and recognizer and mic:
        # --- ONLINE MODE (Always-on Google STT) ---
        print(f"[stt] Listening continuously (will respond when '{WAKE_WORD}' detected)...", flush=True)
        
        # Open microphone ONCE to avoid PyAudio/ALSA initialization overhead every loop
        with mic as source:
            # Short calibration
            recognizer.adjust_for_ambient_noise(source, duration=1)
            
            while True:
                # Check mute status inside loop
                if settings_sync.is_device_muted():
                    print("[voice] Device muted, pausing listening...")
                    time.sleep(2)
                    continue

                if not is_online():
                    # Fallback to offline loop if internet lost
                    break

                # Pass OPEN source to live_stt_listen (zero latency)
                # Timeout 8s to allow silence detection, phrase limit 10s for commands
                text = live_stt_listen(recognizer, source, timeout=8, phrase_time_limit=10.0)
                
                if not text:
                    continue

                text_lower = text.lower()
                print(f"[stt] Heard: '{text}'")

                # Check for any wake word from the list
                detected_wake_word = None
                for wake_word in WAKE_WORDS:
                    if wake_word in text_lower:
                        detected_wake_word = wake_word
                        break
                
                if detected_wake_word:
                    print(f"[wake] ✓ Wake word '{detected_wake_word}' detected!")
                    
                    # Diagnostic: Check network health immediately
                    from .networking import check_network_health
                    threading.Thread(target=check_network_health, daemon=True).start()
                    
                    # Duck volume (visual/audio feedback)
                    if music_proc_holder.get("proc"):
                        set_volume(20)

                    # Play wake sound
                    play_audio_url("https://github.com/Starttoaster/rk-voice/raw/main/wake.wav")
                    
                    # Strip key word to get command
                    idx = text_lower.find(detected_wake_word)
                    command_part = text[idx + len(detected_wake_word):].strip()
                    
                    # If user just said wake word only, listen for follow-up
                    if not command_part:
                        print("[stt] Wake word heard but no command. Listening for follow-up...")
                        # Reuse the SAME source for follow-up
                        try:
                            audio = recognizer.listen(source, timeout=5.0, phrase_time_limit=10.0)
                            command_part = recognizer.recognize_google(audio)
                        except Exception:
                            command_part = ""
                    
                    # Start conversation loop with the command
                    _handle_conversation(command_part, slug, music_proc_holder)
    
    # Fallback / Offline path if loop breaks



        text_lower = text.lower()
        print(f"[stt] Heard: '{text}'")

        # Check for any wake word from the list
        detected_wake_word = None
        for wake_word in WAKE_WORDS:
            if wake_word in text_lower:
                detected_wake_word = wake_word
                break
        
        if detected_wake_word:
            print(f"[wake] ✓ Wake word '{detected_wake_word}' detected!")
            
            # Diagnostic: Check network health immediately
            from .networking import check_network_health
            threading.Thread(target=check_network_health, daemon=True).start()
            
            # Duck volume (visual/audio feedback)
            if music_proc_holder.get("proc"):
                set_volume(20)

            # Play wake sound
            play_audio_url("https://github.com/Starttoaster/rk-voice/raw/main/wake.wav")
            
            # Strip key word to get command
            # Find detection index
            idx = text_lower.find(detected_wake_word)
            # Take everything AFTER the wake word
            command_part = text[idx + len(detected_wake_word):].strip()
            
            # If user just said wake word only, listen for follow-up
            if not command_part:
                print("[stt] Wake word heard but no command. Listening for follow-up...")
                command_part = live_stt_listen(recognizer, mic, timeout=5.0)
            
            # --- CONVERSATION LOOP ---
            # If we enter conversation mode, we keep listening until silence/exit
            
            current_command = command_part
            in_conversation = True
            
            while in_conversation:
                in_conversation = False # Default to exit unless renewed
                
                if current_command:
                    print(f"[stt] Processing command: '{current_command}'")
                    
                    # Execute logic
                    expect_followup = False
                    
                    if match_offline_command(current_command):
                         # Offline command (lights etc)
                         handle_offline_command(current_command, slug)
                         # Note: handle_offline_command already calls speak(), no need to call again
                    else:
                         # Online AI
                         expect_followup = process_online_command(current_command, slug, music_proc_holder)
                    
                    # Restore volume
                    if music_proc_holder.get("proc"):
                        set_volume(80)
                        
                    # If this was a chat/question, keep listening!
                    if expect_followup and is_online():
                        print("[stt] 🗣️ Follow-up mode active. Listening (5s)...")
                        # Visual cue could be added here (e.g. LED blink)
                        
                        # Short listen window
                        follow_up_text = live_stt_listen(recognizer, mic, timeout=5.0, phrase_time_limit=8.0)
                        
                        if follow_up_text:
                            # User said something! Loop again.
                            # Check to avoid looping on "thank you" or "stop"
                            lower_f = follow_up_text.lower()
                            if any(x in lower_f for x in ["stop", "cancel", "thank you", "thanks", "bye", "goodbye"]):
                                print(f"[stt] Conversation ended by user: {follow_up_text}")
                                speak("You're welcome.")
                            else:
                                print(f"[stt] Follow-up heard: '{follow_up_text}'")
                                current_command = follow_up_text
                                in_conversation = True
                                
                                # Duck volume again if music playing
                                if music_proc_holder.get("proc"):
                                    set_volume(20)
                        else:
                            print("[stt] No follow-up heard. Conversation ended.")
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
    
    # 2. INITIAL SPEECH (before waiting for internet, so user hears it immediately)
    start_msg = "Radhe Radhe RK AI assistant is starting up"
    print(f"[main] {start_msg}")
    speak(start_msg)
    time.sleep(1) # Give it a second
    
    # 3. WAIT FOR INTERNET (User requested 2m max)
    wait_for_internet(max_minutes=2.0)
    
    # 4. SET INITIAL VOLUME (ensure we can hear it)
    set_volume(80)

    # Initialize and Calibrate Microphone ONE TIME here
    recognizer = None
    mic = None
    if getattr(audio_utils, "SPEECH_RECOGNITION_AVAILABLE", False) and getattr(audio_utils, "sr", None) is not None:
        try:
            # FORCE HARDWARE GAIN FIRST
            setup_microphone_volume()
            
            print("[stt] Initializing microphone...", flush=True)
            recognizer = audio_utils.sr.Recognizer()
            recognizer.dynamic_energy_threshold = False  # Use fixed threshold
            recognizer.energy_threshold = 50  # Ultra-sensitive for sealed cases
            recognizer.pause_threshold = 1.2   # Wait longer before ending
            recognizer.phrase_threshold = 0.05 # Start INSTANTLY
            recognizer.non_speaking_duration = 0.5  # Long pre-buffer to catch "rk"
            
            from .config import MIC_DEVICE_INDEX
            device_idx = MIC_DEVICE_INDEX
            if device_idx is not None and device_idx < 0:
                device_idx = None
            mic = audio_utils.sr.Microphone(device_index=device_idx)
            
            if mic is not None:
                print("[stt] Calibrating microphone for ambient noise (2 seconds)...", flush=True)
                try:
                    with mic as source:
                        recognizer.adjust_for_ambient_noise(source, duration=2.0)
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
    
    # Start background sync for mute/memory settings from Appwrite
    settings_sync.start_settings_sync()
    
    # Start command poller for mobile app commands
    command_poller.start_command_poller(slug)
    
    # Announce ready right before starting to listen
    ready_msg = "Radhe Radhe RK AI assistant is ready"
    print(f"\n{ready_msg}")
    speak(ready_msg)
    print("")

    # Voice mode: standard wake word loop
    while True:
        try:
            voice_flow(decoder_available, music_proc_holder, slug, recognizer=recognizer, mic=mic)
            time.sleep(0.5) # Throttle loop
        except KeyboardInterrupt:
            break
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            print(f"[main] Error in voice loop: {error_msg}")
            
            # Register error for monitoring
            register_error(
                error_type=f"voice_loop_{error_type}",
                message=error_msg,
                severity="major",
                traceback=tb.format_exc(),
                file_path=__file__
            )
            
            # Check if diagnosis should be triggered
            monitor = get_monitor()
            if monitor.should_trigger_diagnosis():
                print("\n[main] 🚨 Triggering self-diagnosis...\n")
                threading.Thread(
                    target=lambda: self_diagnosis.SelfDiagnosis().run_full_diagnosis(slug),
                    daemon=True
                ).start()
            
            time.sleep(1)


if __name__ == "__main__":
    main()
