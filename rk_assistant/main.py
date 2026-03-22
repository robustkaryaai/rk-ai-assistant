"""
RK AI Pi client v4.0.0  —  SmartSTT Edition

Behavior summary:
  1. Start SmartSTTEngine (always-on background listener).
  2. Main loop: pull commands from engine.command_queue.
  3. Mute: engine stopped; unmuted: engine restarted + TTS announcement.
  4. Night protocol: ambient RMS checked every ~60 s.
     • If consistently quiet → slow STT + suppress TTS (until voice command arrives).
     • When noise returns → restore normal mode + TTS announcement.

Designed for Raspberry Pi.  Uses SpeechRecognition (Google/Groq online) and
PocketSphinx (offline).  No more polling loops — zero startup delay on wake word.
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
import queue
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
    create_stt_engine,
    measure_ambient_rms,
    SmartSTTEngine,
)

# Use Flite-first hybrid TTS with gTTS/espeak fallback
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
    PHRASE_TIME_LIMIT,
    NIGHT_AMBIENT_THRESHOLD,
    NIGHT_CHECK_INTERVAL,
    NIGHT_CONFIRM_COUNT,
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
from . import smart_home
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
    f = open(lock_file, 'w')
    try:
        fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except IOError:
        print("[main] FATAL: Another instance of RK AI Home is already running. Exiting.")
        sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Night Protocol ambient checker
# ─────────────────────────────────────────────────────────────────────────────

class NightProtocolMonitor:
    """
    Runs a background thread that periodically samples ambient noise.
    Calls engine.set_night_mode(True/False) when thresholds are crossed.
    Also manages the TTS-suppression flag used by the main loop.
    """

    def __init__(self, engine: SmartSTTEngine, mic, recognizer):
        self.engine = engine
        self.mic = mic
        self.recognizer = recognizer
        self._quiet_streak = 0          # consecutive quiet readings
        self._loud_streak = 0           # consecutive loud readings
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self.night_tts_suppressed = False   # main loop reads this flag

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True, name="night-protocol")
        self._thread.start()
        print("[night] 🌙 NightProtocolMonitor started.", flush=True)

    def stop(self):
        self._stop_evt.set()

    def _loop(self):
        while not self._stop_evt.is_set():
            # Wait between checks (break into 5 s slices so stop_evt is respected)
            for _ in range(NIGHT_CHECK_INTERVAL // 5):
                if self._stop_evt.is_set():
                    return
                time.sleep(5)

            # 1. Check if the user even WANTS the Night Protocol auto-quiet feature enabled
            if not settings_sync.is_night_protocol_enabled():
                # If they disabled it from the mobile app, force the Pi out of night mode and skip RMS checks
                if self.engine.night_mode:
                    self.engine.set_night_mode(False)
                    self.night_tts_suppressed = False
                    print("[night] ☀️  Night protocol disabled by user app — normal mode restored.", flush=True)
                continue

            # 2. TIME-OF-DAY GATE: Only allow night mode to activate between 10 PM - 7 AM
            import datetime as _dt
            _hour = _dt.datetime.now().hour
            _is_nighttime = _hour >= 22 or _hour < 7  # 10 PM to 7 AM
            if not _is_nighttime:
                # Daytime: if we're somehow in night mode, exit it
                if self.engine.night_mode:
                    self.engine.set_night_mode(False)
                    self.night_tts_suppressed = False
                    print("[night] ☀️  Daytime detected — night mode auto-exited.", flush=True)
                continue  # Skip RMS checks entirely during the day

            # 3. Only run the RMS checking logic if feature is enabled and it's night
            # AGENT FIX: Pause engine to avoid microphone resource clash
            was_running = self.engine._running
            if was_running:
                self.engine.stop()
                time.sleep(0.5) # Give ALSA a breath

            rms = measure_ambient_rms(self.mic, self.recognizer, duration=1.5)
            
            # AGENT FIX: Restart engine immediately after RMS check
            if was_running:
                self.engine.start()

            print(f"[night] Ambient RMS: {rms:.0f} (threshold: {NIGHT_AMBIENT_THRESHOLD})", flush=True)

            if rms < NIGHT_AMBIENT_THRESHOLD and rms > 0:
                self._quiet_streak += 1
                self._loud_streak = 0
            elif rms >= NIGHT_AMBIENT_THRESHOLD:
                self._loud_streak += 1
                self._quiet_streak = 0

            # Enter night mode — only during night hours (already gated above)
            if self._quiet_streak >= NIGHT_CONFIRM_COUNT and not self.engine.night_mode:
                self._quiet_streak = 0
                self.engine.set_night_mode(True)
                self.night_tts_suppressed = True
                print("[night] 🌙 Night protocol active — TTS suppressed.", flush=True)
                # Send push notification to user's phone via backend
                try:
                    import threading as _thr
                    import requests as _rq
                    from .config import BACKEND_BASE_URL
                    from .networking import read_slug as _rs
                    _slug, _ = _rs()
                    if _slug:
                        _thr.Thread(
                            target=lambda: _rq.post(
                                f"{BACKEND_BASE_URL}/device/{_slug}/notify",
                                json={
                                    "title": "RK AI Home 🌙",
                                    "body": "Night mode activated — I'll stay quiet until morning.",
                                    "type": "night_mode"
                                },
                                timeout=5
                            ),
                            daemon=True
                        ).start()
                except Exception as _ne:
                    print(f"[night] Push notification failed: {_ne}", flush=True)

            # Exit night mode
            if self._loud_streak >= 2 and self.engine.night_mode:
                self._loud_streak = 0
                self.engine.set_night_mode(False)
                self.night_tts_suppressed = False
                # Announce end of night mode
                try:
                    speak("Good morning. Night mode ended, I'm fully active again.")
                except Exception:
                    pass
                print("[night] ☀️  Night protocol ended — normal mode restored.", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def play_audio_file_local(filename):
    """Helper to play sounds from the assets folder."""
    p = Path(__file__).parent / "assets" / filename
    if p.exists():
        audio_utils.play_audio_file(str(p))

def trigger_music_playback(query, music_proc_holder):
    """Start music playback in a way that doesn't block the main loop."""
    if music_proc_holder.get("proc"):
        stop_process(music_proc_holder["proc"])
    proc = music_manager.play_music(query)
    if proc:
        music_proc_holder["proc"] = proc

def handle_backend_reply(text, online, music_proc_holder, slug):
    """Process text via Gemini or Backend and handle the response actions."""
    print(f"[gemini] Processing: '{text}'")

    reply_text = ""
    if USE_GEMINI_DIRECT and GEMINI_API_KEY:
        try:
            reply_text = gemini_client.get_conversational_response(text, api_key=GEMINI_API_KEY)
        except Exception as e:
            print(f"[gemini] Direct error: {e}")

    if not reply_text:
        resp = post_text_to_backend(text, slug)
        if isinstance(resp, dict):
            reply_text = resp.get("reply", "")
        else:
            reply_text = str(resp)

    if not reply_text:
        speak("I am having trouble connecting to my brain.")
        return

    print(f"[gemini] Reply: {reply_text}")

    intents = gemini_client.classify_intent(text, api_key=GEMINI_API_KEY)

    for intent_obj in intents:
        intent = intent_obj.get("intent", "general")
        params = intent_obj.get("parameters", {})

        if intent == "music":
            query = reply_text.replace("Searching for", "").replace("Playing", "").strip()
            trigger_music_playback(query, music_proc_holder)
            speak(reply_text)
        elif intent in ("weather", "news"):
            speak(reply_text)
        elif intent in ("cozy_setup", "focus_mode", "open_app"):
            from .desktop_link import trigger_desktop_action
            speak(reply_text)
            trigger_desktop_action(intent, params, slug=slug)
        elif intent == "lumina_coding":
            from . import smart_home
            from .desktop_link import trigger_desktop_action
            smart_home.run_coding_ambience()
            speak(reply_text)
            trigger_desktop_action("lumina_coding_session", params, slug=slug)
        elif intent == "alarm":
            speak(reply_text)
        else:
            speak(reply_text)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    """Main entry point for the assistant."""
    _lock_handle = acquire_lock()
    global is_first_boot

    print("\n" + "="*30)
    print("✓ Initializing RK AI Assistant  v4 (SmartSTT)")
    print("="*30 + "\n")
    print("Radhe Radhe! RK AI assistant is starting up.", flush=True)

    # 0. Identity
    slug_val, _ = read_slug()
    if not slug_val:
        print("[main] No slug found! Using default 000000000", flush=True)
        slug_val = "000000000"

    is_first_boot = "--first-boot" in sys.argv

    # 1. Connectivity
    online = is_online()

    # 0.5 Background managers
    print("[main] Starting background managers...", flush=True)

    def handle_backend_reply_sync(text: str):
        nonlocal online
        if not text:
            return
        mock_holder = {"proc": None}
        handle_backend_reply(text, online, mock_holder, slug_val)

    alarm_manager.start_alarm_checker()
    schedule_manager.start_schedule_monitor(handle_backend_reply_sync)
    command_poller.start_command_poller(slug_val)
    start_reset_monitor()
    command_poller.register_voice_callback(handle_backend_reply_sync)

    # Startup TTS off for --quiet or night handoff flag
    suppress_startup_tts = "--quiet" in sys.argv

    # 2. Startup greeting (early: "starting up" — "ready to rock" plays after STT is live)
    if online:
        greeting = settings_sync.get_greeting_phrase()
        quiet_flag = Path("/tmp/.quiet_startup")
        if quiet_flag.exists():
            print("[startup] Quiet mode active from night update.")
            quiet_flag.unlink()
            suppress_startup_tts = True

        if is_first_boot:
            print("[main] First boot detected.")
            if not suppress_startup_tts:
                speak("Radhe Radhe! RK AI assistant is starting up.")
                time.sleep(0.6)
                speak(f"{greeting}! I have connected to the internet now let me setup my things")
                time.sleep(1)
            sound_path = str(Path(__file__).parent / "sounds" / "preparing.mp3")
            proc = play_audio_url(sound_path)
            if proc:
                proc.wait()
        elif not suppress_startup_tts:
            start_msg = f"{greeting}! RK AI assistant is starting up."
            print(f"[main] {start_msg}")
            speak(start_msg)
            time.sleep(1)

    # 3. Initialize and calibrate microphone
    recognizer = None
    mic = None
    if getattr(audio_utils, "SPEECH_RECOGNITION_AVAILABLE", False) and getattr(audio_utils, "sr", None) is not None:
        try:
            setup_microphone_volume()
            print("[stt] Initializing microphone... (Suppressing ALSA logs)", flush=True)

            with audio_utils.no_alsa_err():
                recognizer = audio_utils.sr.Recognizer()
                recognizer.dynamic_energy_threshold = True
                recognizer.energy_threshold = 300
            recognizer.pause_threshold = 1.2
            recognizer.phrase_threshold = 0.3
            recognizer.non_speaking_duration = 0.8

            from .config import MIC_DEVICE_INDEX, MIC_DEVICE_NAME
            device_idx = MIC_DEVICE_INDEX

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
                            recognizer.adjust_for_ambient_noise(source, duration=5.0)
                            print(f"[stt] Done! Energy threshold set to: {recognizer.energy_threshold}")
                except Exception as e:
                    print(f"[stt] Calibration failed: {e}")
        except Exception as e:
            print(f"[stt] Error during microphone setup: {e}")

    # 4. Create SmartSTTEngine
    stt_engine: Optional[SmartSTTEngine] = None
    if recognizer and mic:
        stt_engine = create_stt_engine(recognizer, mic, online=online)
        stt_engine.start()
    else:
        print("[main] ⚠️  No microphone available — STT engine not started.", flush=True)

    # 5. Start Night Protocol Monitor
    night_monitor: Optional[NightProtocolMonitor] = None
    if stt_engine and mic and recognizer:
        night_monitor = NightProtocolMonitor(stt_engine, mic, recognizer)
        night_monitor.start()

    music_proc_holder = {"proc": None}
    if stt_engine:
        print("[main] Radhe Radhe! RK AI Assistant is ready to rock (SmartSTT active).", flush=True)
        if not suppress_startup_tts:
            speak("Radhe Radhe! RK AI Assistant is ready to rock.")
    else:
        print("[main] RK AI Assistant running without STT (no microphone).", flush=True)

    # ─── MAIN LOOP ───────────────────────────────────────────────────────────
    was_muted = False

    while True:
        try:
            # ── Mute detection ─────────────────────────────────────────────
            from .command_poller import get_mute_state
            is_muted = get_mute_state()

            if is_muted:
                if not was_muted:
                    # Transitioning INTO mute
                    print("[main] 🔇 Device muted — stopping STT engine.", flush=True)
                    if stt_engine:
                        stt_engine.stop()
                    was_muted = True

                report_state(slug_val, "muted")
                update_activity()
                time.sleep(2)
                continue

            if was_muted:
                # Transitioning out of mute → restart engine + announce
                print("[main] 🔊 Device unmuted — restarting STT engine.", flush=True)
                if stt_engine:
                    stt_engine.online = is_online()
                    stt_engine.restart()
                else:
                    # Engine was never created (no mic during boot), try to rebuild
                    if recognizer and mic:
                        stt_engine = create_stt_engine(recognizer, mic, online=is_online())
                        stt_engine.start()

                # Announce unmute via TTS
                try:
                    speak("Device unmuted. I'm listening again.")
                except Exception:
                    pass
                was_muted = False

            update_activity()
            online = is_online()

            # Keep engine online flag in sync
            if stt_engine and stt_engine.online != online:
                stt_engine.set_online(online)

            report_state(slug_val, "idle")

            # ── Night TTS suppression flag ──────────────────────────────────
            night_tts_suppressed = (night_monitor.night_tts_suppressed
                                    if night_monitor else False)

            # ── Wait for a command from the engine ─────────────────────────
            report_state(slug_val, "listening")
            if stt_engine:
                try:
                    text = stt_engine.command_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
            else:
                # Fallback: old blocking wake-word loop (no mic scenario)
                detected = audio_utils.wait_for_wake_word(
                    use_offline=(not online), recognizer=recognizer, mic=mic
                )
                if not detected:
                    continue
                if recognizer and mic:
                    text = audio_utils.live_stt_listen(
                        recognizer, mic, slug_val,
                        timeout=10, phrase_time_limit=PHRASE_TIME_LIMIT
                    )
                else:
                    audio_path = record_until_silence(silence_duration=SILENCE_TIMEOUT)
                    text = online_stt(audio_path) if audio_path else ""

            if not text or text == "__WAKE__":
                # Bare wake word with no command — prompt user
                play_audio_file_local("listen.wav")
                if not night_tts_suppressed:
                    # In night mode we stay silent until user actually says something
                    pass
                # Wait up to 6 s for a follow-up command
                if stt_engine:
                    try:
                        text = stt_engine.command_queue.get(timeout=6.0)
                    except queue.Empty:
                        print("[main] No follow-up command heard.")
                        continue
                else:
                    continue

            if not text:
                continue

            update_activity()
            print(f"[main] Command received: '{text}'", flush=True)
            report_state(slug_val, "thinking")

            # ── Play listen chime ─────────────────────────────────────────
            play_audio_file_local("listen.wav")

            # ── In night mode, TTS is now un-suppressed FOR THIS response
            # (night_monitor.night_tts_suppressed stays True until noise returns,
            #  but the speak() calls below will fire for this single response)
            # ── This is intentional: user explicitly spoke → they want TTS

            # ── Smart Home Fast Intercept ─────────────────────────────────
            if smart_home.is_smart_home_intent(text):
                print("[main] Smart Home Intent detected (Local Intercept)")
                resp = smart_home.execute_smart_command(text)
                speak(resp)
                continue

            # ── Quick media/offline command shortcut ──────────────────────
            offline_kw = match_offline_command(text.lower())
            if offline_kw in ("stop", "pause", "resume", "volume up", "volume down",
                              "mute", "unmute"):
                print(f"[main] Quick command: {offline_kw}")
                resp = process_offline_command(offline_kw, text, music_proc_holder.get("proc"))
                if resp:
                    speak(resp)
                continue

            if online:
                # ── Full offline command check first ──────────────────────
                offline_kw2 = match_offline_command(text.lower())
                if offline_kw2:
                    resp = process_offline_command(
                        offline_kw2, text, music_proc_holder.get("proc")
                    )
                    if resp and isinstance(resp, str):
                        if resp.startswith("_PLAY_MUSIC_|"):
                            trigger_music_playback(resp.split("|", 1)[1], music_proc_holder)
                        elif resp == "_RK_UPDATE_":
                            speak("Checking for updates and restarting.")
                            subprocess.run(["git", "pull", "origin", "main"],
                                           cwd=str(Path(__file__).parent.parent))
                            subprocess.run(["sudo", "systemctl", "restart",
                                            "rk-assistant.service"])
                            return
                        elif resp == "_RK_SHUTDOWN_":
                            speak("Shutting down the system.")
                            subprocess.run(["sudo", "shutdown", "-h", "now"])
                            return
                        elif resp == "_RK_REBOOT_":
                            speak("Rebooting the system.")
                            subprocess.run(["sudo", "reboot"])
                            return
                        elif resp == "_PLAY_AGAIN_":
                            if music_manager.last_played_query:
                                trigger_music_playback(
                                    music_manager.last_played_query, music_proc_holder
                                )
                        else:
                            speak(resp)
                    continue

                # ── Gemini / Backend path ─────────────────────────────────
                handle_backend_reply(text, online, music_proc_holder, slug_val)

            else:
                # ── Offline mode ──────────────────────────────────────────
                text_lower = text.lower()
                offline_kw = match_offline_command(text_lower)

                if offline_kw:
                    resp = process_offline_command(
                        offline_kw, text, music_proc_holder.get("proc")
                    )
                    if resp and isinstance(resp, str):
                        if resp.startswith("_PLAY_MUSIC_|"):
                            trigger_music_playback(resp.split("|", 1)[1], music_proc_holder)
                        elif resp == "_RK_UPDATE_":
                            speak("Checking for updates and restarting.")
                            subprocess.run(["git", "pull", "origin", "main"],
                                           cwd=str(Path(__file__).parent.parent))
                            subprocess.run(["sudo", "systemctl", "restart",
                                            "rk-assistant.service"])
                            return
                        elif resp == "_RK_SHUTDOWN_":
                            speak("Shutting down the system.")
                            subprocess.run(["sudo", "shutdown", "-h", "now"])
                            return
                        elif resp == "_RK_REBOOT_":
                            speak("Rebooting the system.")
                            subprocess.run(["sudo", "reboot"])
                            return
                        elif resp == "_PLAY_AGAIN_":
                            if music_manager.last_played_query:
                                trigger_music_playback(
                                    music_manager.last_played_query, music_proc_holder
                                )
                        else:
                            speak(resp)
                else:
                    print("[stt] No offline intent matched.")

        except Exception as e:
            print(f"[main] Error in main loop: {e}")
            tb.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    slug_val = "000000000"
    try:
        from .networking import read_slug
        slug_val, _ = read_slug()
    except Exception:
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

        try:
            from .self_diagnosis import run_immediate_diagnosis
            run_immediate_diagnosis(
                slug=slug_val or "000000000",
                error_type=type(e).__name__,
                message=error_msg,
                traceback_str=traceback_str,
            )
        except Exception as diag_e:
            print(f"[main] Self-diagnosis failed to start: {diag_e}")

        sys.exit(1)
