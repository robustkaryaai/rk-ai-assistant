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
import os
import sys
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

from .config import ERROR_LOG_FILE, LAST_AUDIO, WAKE_WORD, WAKE_WORDS, BACKEND_BASE_URL, GEMINI_API_KEY, GEMINI_API_KEY_BACKUP, GEMINI_MODEL, USE_GEMINI_DIRECT
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
)
from .offline_commands import match_offline_command, process_offline_command
from .weather_news import fetch_news, fetch_weather
from .intent_classifier import guess_fallback_intent, start_pending_request_msg
from .reset_monitor import start_reset_monitor
from . import gemini_client
from . import local_handlers
from . import settings_sync  # Sync mute/memory from Appwrite
from . import command_poller  # Poll and execute commands from mobile app
from .error_monitor import register_error, get_monitor
from . import self_diagnosis
from . import music_manager
from difflib import SequenceMatcher

def _is_wake_word_heard(text: str, wake_words, threshold: float = 0.88):
    """Fuzzy match spoken text against wake words."""
    text = text.lower().strip()

    for w in wake_words:
        ratio = SequenceMatcher(None, text, w).ratio()
        if ratio >= threshold:
            return w

        # also check per-word matching
        for token in text.split():
            if SequenceMatcher(None, token, w).ratio() >= threshold:
                return w

    return None





def _speak_twice(text: str) -> None:
    if not text:
        return
    speak(text)
    time.sleep(0.2)
    speak(text)

def handle_local_response(response: str) -> None:
    """Check if the response is a special audio sentinel, else speak it."""
    if not response:
        return
    if response.startswith("_PLAY_OFFLINE_"):
        try:
            idx = response.split("_")[3]
            sound_path = str(Path(__file__).parent / "sounds" / f"offline_{idx}.mp3")
            proc = play_audio_url(sound_path)
            if proc: proc.wait()
        except Exception as e:
            print(f"[audio] Failed to play offline mp3: {e}")
            speak("I received your offline command.")
    else:
        speak(response)


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
        write_slug(slug, verified=False)
        print(f"[slug] Generated new slug: {slug}")
    
    # Check if we are online before trying the backend
    if not is_online():
        print(f"[slug] Offline: Skipping backend ensure for slug: {slug}")
        return slug

    # Use backend ensure endpoint (auto-creates if needed)
    try:
        url = f"{BACKEND_BASE_URL}/device/ensure/{slug}"
        print(f"[slug] Ensuring device exists in backend...", flush=True)
        resp = requests.post(url, timeout=30)
        if resp.ok:
            write_slug(slug, verified=True)
            print(f"[slug] ✓ Device verified in backend.")
        else:
            print(f"[slug] Backend ensure failed (HTTP {resp.status_code}), continuing...")
    except Exception as e:
        print(f"[slug] Could not ensure device: {e}, continuing...")
    
    return slug





def handle_backend_reply(reply_obj: dict, music_proc_holder: dict, slug: str, decoder_available: bool = False, original_text: str = "") -> None:
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


def _send_to_backend_and_handle(text: str, slug: str, music_proc_holder: dict) -> None:
    """Send text to backend and handle the response (speak it)."""
    def _handler():
        try:
            print(f"[backend] Sending request: '{text}'...", flush=True)
            # This blocks this thread until response arrives (which is fine, it's a daemon thread)
            response = post_text_to_backend(text, slug)
            
            if response:
                print(f"[backend] Received response: {response}", flush=True)
                handle_backend_reply(response, music_proc_holder, slug)
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


def trigger_music_playback(query, music_proc_holder):
    """Start music playback in a background thread and update proc holder."""
    def _run():
        from .music_manager import play_music
        proc = play_music(query)
        if proc:
            # Clean up old proc
            old_proc = music_proc_holder.get("proc")
            if old_proc:
                try:
                    import os, signal
                    os.killpg(os.getpgid(old_proc.pid), signal.SIGTERM)
                except:
                    old_proc.terminate()
            music_proc_holder["proc"] = proc
            music_proc_holder["last_query"] = query
            
    import threading
    threading.Thread(target=_run, daemon=True).start()

def autoplay_monitor(music_proc_holder, slug):
    """Background loop to detect when a song ends and trigger autoplay."""
    print("[autoplay] Monitor started.", flush=True)
    import time
    from .music_manager import get_related_song_recommendation, current_player
    
    while True:
        try:
            proc = music_proc_holder.get("proc")
            # If a song was playing but now it's finished (and not paused by us)
            if proc and proc.poll() is not None:
                print("[autoplay] Song finished! Finding related track...", flush=True)
                # Clear the finished proc
                music_proc_holder["proc"] = None
                
                # Get recommendation
                last_query = music_proc_holder.get("last_query")
                if last_query:
                    recommendation = get_related_song_recommendation(last_query)
                    if recommendation:
                        print(f"[autoplay] ♾️ Autoplay: Next song is '{recommendation}'", flush=True)
                        speak(f"Playing related song: {recommendation}")
                        trigger_music_playback(recommendation, music_proc_holder)
                    else:
                        print("[autoplay] No recommendation found.", flush=True)
            
            time.sleep(5) # Check every 5s
        except Exception as e:
            print(f"[autoplay] Error: {e}")
            time.sleep(10)

def update_monitor():
    """Background thread to check for updates and handle critical ones."""
    import subprocess
    import time
    from .audio_utils_simple import speak
    # Detect the actual project root dynamically
    import os as _os
    _project_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    # Wait 1 min after startup before first check
    time.sleep(60)
    while True:
        try:
            print("[update] 📡 Checking for updates...")
            subprocess.run(["git", "fetch", "origin"], capture_output=True, cwd=_project_dir)
            
            res = subprocess.run(["git", "log", "HEAD..origin/main", "--oneline"],
                                  capture_output=True, text=True, cwd=_project_dir)
            if res.stdout.strip():
                print(f"[update] 📥 Update available: {res.stdout.strip().splitlines()[0]}")
                diff_log = res.stdout.lower()
                if "critical" in diff_log:
                    print("[update] 🚨 Critical update detected!")
                    speak("Critical update found. Updating and restarting.")
                    subprocess.run(["git", "pull", "origin", "main"], capture_output=True, cwd=_project_dir)
                    subprocess.run(["sudo", "systemctl", "restart", "rk-assistant.service"])
                    break
            
            time.sleep(30 * 60)
        except Exception as e:
            print(f"[update] Error: {e}")
            time.sleep(300)

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
        from . import music_manager
        music_manager.pause_music()
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
            from .config import GEMINI_MODEL_PRIMARY, GEMINI_MODEL_FALLBACK
            intents = gemini_client.classify_intent(
                text, 
                api_key=GEMINI_API_KEY, 
                backup_key=GEMINI_API_KEY_BACKUP, 
                model_name=GEMINI_MODEL_PRIMARY,
                fallback_model=GEMINI_MODEL_FALLBACK
            )
            local_intents = ["music", "alarm", "announcement", "chat", "general", "stop_alarm", "emergency_alarm", "fire_alarm", "remember", "task", "weather", "news"]
            backend_intents = ["image", "video", "docx", "ppt", "note", "planner", "timetable", "lesson_plan", "exam_paper", "grading_sheet", "class_planner", "teacher_note"]
            
            if intents and len(intents) > 0:
                first_intent = intents[0]
                intent_name = first_intent.get("intent", "general")
                parameters = first_intent.get("parameters", {})
                
                if intent_name in local_intents:
                    response = local_handlers.handle_intent(intent_name, parameters, original_text=text)
                    
                    # Special handling for local music
                    if response.get("intent") == "music_local":
                        query = response.get("query")
                        speak(f"Searching for {query}...")
                        trigger_music_playback(query, music_proc_holder)
                        return False # Music playing, don't follow up immediately
                            
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
                    # Default: Send to backend if not local
                    needs_backend_ack = True
                    _send_to_backend_and_handle(text, slug, music_proc_holder)
                    return False
            else:
                # No intents found
                needs_backend_ack = True
                _send_to_backend_and_handle(text, slug, music_proc_holder)
                return False
                
        except Exception as e:
            print(f"[gemini] Error in processing: {e}")
            speak("Sorry, I had trouble reaching the server.")
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
    ONLINE: Uses high-speed STT continuously to listen. If 'rk' is in text, executes command.
    OFFLINE: Falls back to PocketSphinx for wake word.
    """
    # Check if device is muted (synced from Appwrite via mobile app)
    if settings_sync.is_device_muted():
        print("[voice] Device is muted, skipping listening...")
        time.sleep(2)
        return
    
    # 1. Determine mode
    online = is_online()
    
    if online and recognizer and mic:
        # --- ONLINE MODE (Always-on high-speed STT) ---
        print(f"[stt] Listening continuously (will respond when '{WAKE_WORD}' detected)...", flush=True)
        
        # Open microphone ONCE to avoid PyAudio/ALSA initialization overhead every loop
        with mic as source:
            # Recognizer is already calibrated at startup in main()
            # We keep its threshold unless dynamic adjustment is disabled
            recognizer.dynamic_energy_threshold = True
            recognizer.pause_threshold = 0.8
            
            consecutive_offline_checks = 0
            last_activity_time = time.time()
            
            while True:
                # 1. Check for Inactivity (5 Minute "Night Protocol" fix)
                # If no speech for 5 minutes, reset the mic stream to keep it fresh
                current_time = time.time()
                if current_time - last_activity_time > 300:
                    print(f"[stt] Inactivity threshold reached (5m). Refreshing system state...", flush=True)
                    # We break the loop to allow main() to restart voice_flow, 
                    # which re-opens the microphone and resets the stream.
                    break

                # 2. Check mute status inside loop
                if settings_sync.is_device_muted():
                    print("[voice] Device muted, pausing listening...")
                    time.sleep(2)
                    continue

                # Shoom resilience: don't go offline on a single failure
                if not is_online():
                    consecutive_offline_checks += 1
                    if consecutive_offline_checks >= 3:
                        print("[stt] Internet connection lost (3 failed checks). Switching to offline mode...", flush=True)
                        break
                    else:
                        print(f"[stt] Warning: Internet check failed ({consecutive_offline_checks}/3). Continuing...", flush=True)
                        time.sleep(1)
                        continue
                else:
                    consecutive_offline_checks = 0

                # Pass OPEN source to live_stt_listen (zero latency)
                text = live_stt_listen(recognizer, source, slug, timeout=8, phrase_time_limit=10.0)
                
                if not text:
                    continue

                # Reset inactivity timer on speech detection
                last_activity_time = time.time()
                
                text_lower = text.lower()
                print(f"[stt] Heard: '{text}'")

                # Check for any wake word from the list
                detected_wake_word = _is_wake_word_heard(text_lower, WAKE_WORDS)

                if detected_wake_word:
                    print(f"[wake] ✓ Wake word '{detected_wake_word}' detected!")
                    
                    # Duck volume (visual/audio feedback)
                    if music_proc_holder.get("proc"):
                        music_manager.pause_music()
                    
                    # Strip key word to get command
                    idx = text_lower.find(detected_wake_word)
                    command_part = text[idx + len(detected_wake_word):].strip()
                    
                    # If user just said wake word only, listen for follow-up
                    if not command_part:
                        print("[stt] Wake word heard but no command. Listening for follow-up...")
                        try:
                            audio = recognizer.listen(source, timeout=5.0, phrase_time_limit=10.0)
                            command_part = recognizer.recognize_google(audio)
                        except Exception:
                            command_part = ""
                    
                    # --- CONVERSATION LOOP ---
                    current_command = command_part
                    in_conversation = True
                    
                    while in_conversation:
                        in_conversation = False # Default to exit unless renewed
                        
                        if current_command:
                            print(f"[stt] Processing command: '{current_command}'")
                            
                            # --- FAST TRACK (Instant local execution for UX) ---
                            fast_cmd = current_command.lower().strip()
                            if any(x in fast_cmd for x in ["louder", "quieter", "volume up", "volume down", "mute", "unmute", "stop", "pause", "resume", "play again", "replay"]):
                                 print(f"[main] ⚡ Fast Track: {fast_cmd}")
                                 resp = process_offline_command(fast_cmd, current_command, music_proc_holder.get("proc"))
                                 
                                 if str(resp).startswith("_PLAY_MUSIC_|"):
                                     query = resp.split("|", 1)[1]
                                     proc = music_manager.play_music(query)
                                     if proc: music_proc_holder["proc"] = proc
                                     return
                                 elif resp == "_PLAY_AGAIN_":
                                     query = music_manager.last_played_query
                                     if query: trigger_music_playback(query, music_proc_holder)
                                     return
                                 elif resp == "_RK_UPDATE_":
                                     speak("Checking for updates and restarting.")
                                     import subprocess
                                     subprocess.run(["git", "pull", "origin", "main"], cwd="/home/raspberrypi/rk-ai-assistant-main")
                                     subprocess.run(["sudo", "systemctl", "restart", "rk-assistant.service"])
                                     return
                                 elif resp == "_RK_SHUTDOWN_":
                                     speak("Shutting down the system.")
                                     import subprocess
                                     subprocess.run(["sudo", "shutdown", "-h", "now"])
                                     return
                                 elif resp == "_RK_REBOOT_":
                                     speak("Rebooting the system.")
                                     import subprocess
                                     subprocess.run(["sudo", "reboot"])
                                     return

                                 if any(x in fast_cmd for x in ["louder", "quieter", "volume", "resume"]):
                                     if music_proc_holder.get("proc"):
                                        music_manager.unpause_music()
                                        
                                 if fast_cmd in ["wake", "wake up", "restart stt", "refresh"]:
                                     speak("Refreshing systems.")
                                     return # Break voice_flow to restart mic

                                 if "volume" in fast_cmd or "louder" in fast_cmd or "quieter" in fast_cmd:
                                     continue 
                                     
                            # --- NORMAL TRACK ---
                            expect_followup = False
                            offline_kw = match_offline_command(current_command)
                            is_conversational = offline_kw in ["hello", "hi", "hey", "how are you", "what's up", "thank you", "thanks", "goodbye", "bye"]
                            
                            if offline_kw and (not online or not is_conversational):
                                 resp = process_offline_command(offline_kw, current_command, music_proc_holder.get("proc"))
                                 if resp:
                                     if str(resp).startswith("_PLAY_MUSIC_|"):
                                         query = resp.split("|", 1)[1]
                                         proc = music_manager.play_music(query)
                                         if proc: music_proc_holder["proc"] = proc
                                     elif resp == "_PLAY_AGAIN_":
                                         query = music_manager.last_played_query
                                         if query: trigger_music_playback(query, music_proc_holder)
                                     else:
                                         speak(resp)
                            else:
                                 expect_followup = process_online_command(current_command, slug, music_proc_holder)
                            
                            # Restore volume
                            if music_proc_holder.get("proc"):
                                music_manager.unpause_music()
                                
                            # If this was a chat/question, keep listening!
                            if expect_followup and is_online():
                                print("[stt] 🗣️ Follow-up mode active. Listening (5s)...")
                                follow_up_text = live_stt_listen(recognizer, mic, slug, timeout=5.0, phrase_time_limit=8.0)
                                
                                if follow_up_text:
                                    lower_f = follow_up_text.lower()
                                    if any(x in lower_f for x in ["stop", "cancel", "thank you", "thanks", "bye", "goodbye"]):
                                        print(f"[stt] Conversation ended by user: {follow_up_text}")
                                        speak("You're welcome.")
                                    else:
                                        print(f"[stt] Follow-up heard: '{follow_up_text}'")
                                        current_command = follow_up_text
                                        in_conversation = True
                                        if music_proc_holder.get("proc"):
                                            music_manager.pause_music()
                                else:
                                    print("[stt] No follow-up heard.")
                        else:
                            print("[stt] No command heard after wake word.")
                            if music_proc_holder.get("proc"):
                                music_manager.unpause_music()

    elif not online:
        # --- OFFLINE MODE (Porcupine + WebRTC + Vosk) ---
        print("\n[stt] 📡 Running in OFFLINE mode.", flush=True)
        detected = audio_utils.wait_for_wake_word(use_offline=True)
        
        if detected:
            print("[stt] Wake word detected. Recording command...", flush=True)
            audio_path = audio_utils.record_audio()
            
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
                             import subprocess
                             subprocess.run(["git", "pull", "origin", "main"], cwd="/home/raspberrypi/rk-ai-assistant-main")
                             subprocess.run(["sudo", "systemctl", "restart", "rk-assistant.service"])
                             return
                        elif resp == "_RK_SHUTDOWN_":
                             speak("Shutting down the system.")
                             import subprocess
                             subprocess.run(["sudo", "shutdown", "-h", "now"])
                             return
                        elif resp == "_RK_REBOOT_":
                             speak("Rebooting the system.")
                             import subprocess
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
                     print("[stt] Vosk transcribed nothing.")
            else:
                print("[stt] Nothing recorded (silence).")

    # Outside the main loops (usually unreachable unless loop breaks)
    set_volume(80)





def main():
    """Main entry point for the assistant."""
    global is_first_boot
    
    print("\n" + "="*30)
    print("Initializing RK AI Assistant...")
    print("="*30 + "\n")

    # 0. Basic Setup & Identity
    slug_val, _ = read_slug()
    if not slug_val:
        print("[main] No slug found! Using default 000000000", flush=True)
        slug_val = "000000000"

    is_first_boot = "--first-boot" in sys.argv

    # 1. Check internet connectivity immediately
    online = is_online()
    
    # 2. Normal Startup Greeting
    if online:
        if is_first_boot:
            print("[main] First boot detected.")
            # Move the Wi-Fi connected announcement here so it plays through the speaker
            speak("I have connected to the internet now let me setup my things")
            time.sleep(1)
            
            sound_path = str(Path(__file__).parent / "sounds" / "preparing.mp3")
            proc = play_audio_url(sound_path)
            if proc: proc.wait()
        else:
            start_msg = "Radhe Radhe RK AI assistant is starting up"
            print(f"[main] {start_msg}")
            speak(start_msg)
            time.sleep(1)
        
        # ... REST OF THE FUNCTION CONTINUES ...
    


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
                recognizer.energy_threshold = 120 
            recognizer.pause_threshold = 0.8   
            recognizer.phrase_threshold = 0.3 
            recognizer.non_speaking_duration = 0.5 
            
            from .config import MIC_DEVICE_INDEX, MIC_DEVICE_NAME
            device_idx = MIC_DEVICE_INDEX
            
            # Find clean_mic index if configured
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
                print("[stt] Calibrating microphone for ambient noise (10 seconds)...", flush=True)
                try:
                    with audio_utils.no_alsa_err():
                        with mic as source:
                            recognizer.adjust_for_ambient_noise(source, duration=10.0)
                            # Re-force threshold if calibration drifted too high
                        if recognizer.energy_threshold > 600:
                            print(f"[stt] Calibration result very high ({recognizer.energy_threshold}), clamping to 600 for noise resilience.")
                            recognizer.energy_threshold = 600
                        else:
                            print(f"[stt] Energy threshold set to: {recognizer.energy_threshold}", flush=True)
                except Exception as e:
                     print(f"[stt] Warning: Ambient calibration failed: {e}", flush=True)

        except Exception as e:
            print(f"[stt] CRITICAL: Failed to initialize microphone: {e}", flush=True)
            # Register error
            register_error(
                error_type="mic_init_error",
                message=str(e),
                severity="critical",
                traceback=tb.format_exc(),
                file_path=__file__
            )
            # If we are offline and mic fails, we are in trouble, but let's try to keep the process alive
            # for the background hotspot thread.
            print("[main] Warning: Mic failed, but keeping process alive for setup threads.", flush=True)

    
    slug = ensure_valid_slug()
    if not slug:
        print("Missing or invalid slug.txt (must contain 9-digit code).", file=sys.stderr)
        return

    if is_first_boot:
        print("[main] First boot preparation complete.")
        # Create flag to indicate first boot setup is finished
        try:
            flag_path = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / ".first_boot_done"
            flag_path.touch()
            print(f"[main] Standard mode enabled for future boots.")
        except Exception as e:
            print(f"[main] Warning: Could not create first boot flag: {e}")

        sound_path = str(Path(__file__).parent / "sounds" / "prepared.mp3")
        proc = play_audio_url(sound_path)
        if proc: proc.wait()
        time.sleep(1)
        
        # FINAL CELEBRATION!
        print("[main] LOUD AND CLEAR: WE DID IT!")
        speak("We did it!")
        time.sleep(1)

    print("\n" + "="*60)
    print("RK AI ASSISTANT STARTUP")
    print(f"Device Slug: {slug}")
    print("="*60)

    # Initialize variables needed for voice_flow
    decoder_available = load_vosk_model()
    music_proc_holder = {"proc": None, "last_query": None}
    
    # Start background sync for mute/memory settings from Appwrite
    try:
        settings_sync.start_settings_sync(slug)
    except Exception as e:
        print(f"[sync] Failed to start settings sync: {e}")
        
    # Start background music index sync (Populate missing songs)
    try:
        from .music_manager import sync_music_index
        t_music = threading.Thread(target=sync_music_index, daemon=True)
        t_music.start()
    except Exception as e:
        print(f"[main] Music sync error: {e}")
    
    # Start command poller for mobile app commands
    try:
        def on_app_command(text):
             print(f"[app] Received command: {text}")
             # Check for offline commands first (e.g. stop music, volume)
             offline_id = match_offline_command(text)
             if offline_id:
                 resp = process_offline_command(offline_id, text, music_proc_holder.get("proc"))
                 if resp:
                     if str(resp).startswith("_PLAY_MUSIC_|"):
                         query = resp.split("|", 1)[1]
                         proc = music_manager.play_music(query)
                         if proc: music_proc_holder["proc"] = proc
                     elif resp == "_PLAY_AGAIN_":
                         query = music_manager.last_played_query
                         if query: trigger_music_playback(query, music_proc_holder)
                     else:
                         handle_local_response(resp)
             else:
                 # Online processing
                 process_online_command(text, slug, music_proc_holder)

        command_poller.register_voice_callback(on_app_command)
        command_poller.start_command_poller(slug)
    except Exception as e:
        print(f"[commands] Failed to start command poller: {e}")
    
    
    # Start background autoplay monitor (Infinite loop)
    try:
        t_auto = threading.Thread(target=autoplay_monitor, args=(music_proc_holder, slug), daemon=True)
        t_auto.start()
        
        # Start background update monitor
        t_upd = threading.Thread(target=update_monitor, daemon=True)
        t_upd.start()

        # Launch the independent maintenance poller script
        import subprocess
        poller_path = str(Path(__file__).parent / "rk_maintenance_poller.py")
        poller_proc = subprocess.Popen([sys.executable, "-u", poller_path], stdout=sys.stdout, stderr=sys.stderr, start_new_session=True)
        print("[main] Launched independent maintenance poller background process.")
    except Exception as e:
        print(f"[main] Autoplay/Update monitor error: {e}")

    # Start hardware reset button monitor (GPIO 17)
    try:
        start_reset_monitor()
    except Exception as e:
        print(f"[main] Failed to start reset monitor: {e}")

    # --- 6. Start Backend Command Polling (Background) ---
    # Disabled to stop 500 error spam while debugging voice
    # if online:
    #    check_thread = threading.Thread(target=check_commands_loop, args=(slug, music_proc_holder), daemon=True)
    #    check_thread.start()
    #    print("[commands] Background command poller started")
    
    # --- 7. Voice Loop ---
    print("\n" + "="*30)
    print("STARTING VOICE MODE")
    print("="*30 + "\n")
    
    # Announce ready right before starting to listen (skip if first boot since we already spoke)
    if not is_first_boot:
        ready_msg = "Radhe Radhe RK AI assistant is ready"
        print(f"🔊 {ready_msg}")
        speak(ready_msg)

    # Voice mode: standard wake word loop (with robust self-diagnosis)
    print(f"[main] Entering voice loop for slug: {slug}")
    while True:
        try:
            voice_flow(decoder_available, music_proc_holder, slug, recognizer=recognizer, mic=mic)
            time.sleep(0.5) # Throttle loop
        except KeyboardInterrupt:
            print("[main] KeyboardInterrupt received, exiting...")
            if 'poller_proc' in locals() and poller_proc is not None:
                poller_proc.terminate()
            break
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            print(f"[main] Error in voice loop: {error_msg}")
            # Log the full traceback for debugging (to stdout so it shows in journalctl)
            tb.print_exc()
            
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
            
            time.sleep(2)


if __name__ == "__main__":
    main()
