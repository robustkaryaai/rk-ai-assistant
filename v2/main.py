import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from config import (
    BACKEND_BASE_URL,
    DEVICE_SLUG,
    BLUETOOTH_HCI,
    BLUETOOTH_SPEAKER_MAC,
    AUDIO_CACHE_DIR,
)
from router import FastCommandRouter
from backend.client import RKHomeClient
from audio.player import AudioPlayer
from audio.tts import TTSManager
from audio.recorder import AudioRecorder
from audio.streamer import LocalMusicStreamer
from hardware.adapter import BluetoothAdapterManager
from core.alarm_manager import AlarmScheduleManager
from core.pomodoro import PomodoroTimer
from core.quiz_engine import VoiceQuizEngine
from core.diagnostics import SystemDiagnostics
from core.conversation import ConversationEngine
from core.remote_sync import RemoteSyncManager
from core.error_monitor import get_error_monitor
from core.weather import WeatherService
from core.automation import AutomationEngine
from core.sound_monitor import SoundEventMonitor
from audio.spotify import SpotifyManager
from hardware.mic import HardwareMicManager
from llm.offline_llm import OfflineLLM

class RKV2Assistant:
    def __init__(self):
        print("==================================================")
        print("🚀 RK AI Assistant V2 (Pi Zero W / 512MB RAM)")
        print(f"📍 Device Slug:  {DEVICE_SLUG}")
        print(f"📶 BT Adapter:   {BLUETOOTH_HCI} (Strict)")
        print(f"🔊 Speaker MAC:  {BLUETOOTH_SPEAKER_MAC}")
        print(f"🌐 Backend Host: {BACKEND_BASE_URL}")
        print("==================================================")

        # 0. Error Monitor & Self-Diagnosis
        self.error_monitor = get_error_monitor()

        # 1. Hardware Pinning & Watchdog (Strict hci1)
        BluetoothAdapterManager.verify_or_reboot()

        # 2. Audio & Backend Subsystems
        self.player = AudioPlayer()
        self.tts = TTSManager(AUDIO_CACHE_DIR)
        self.client = RKHomeClient(BACKEND_BASE_URL, DEVICE_SLUG)
        self.spotify = SpotifyManager()

        # 3. Core Engines
        self.data_dir = BASE_DIR / "data"
        self.recorder = AudioRecorder(self.data_dir)
        self.alarm_mgr = AlarmScheduleManager(self.data_dir, client=self.client, player=self.player, tts=self)
        self.pomodoro = PomodoroTimer(self.alarm_mgr, tts=self)
        self.quiz = VoiceQuizEngine(tts=self)
        self.conversation = ConversationEngine(client=self.client, tts=self, player=self.player)
        self.remote_sync = RemoteSyncManager(client=self.client, assistant=self, player=self.player, tts=self)
        self.automation = AutomationEngine(assistant=self)
        self.sound_monitor = SoundEventMonitor(client=self.client, tts=self)

        # 4. Offline LLM fallback (Qwen2.5-0.5B Q4_K_M — activates when internet is down)
        self.offline_llm = OfflineLLM()
        if self.offline_llm.is_ready:
            print("🧠 [OfflineLLM] Qwen2.5-0.5B Q4_K_M ready — offline fallback active")
        else:
            print("⚠️  [OfflineLLM] Not available — run: python3 v2/llm/download_model.py")

    def play_ready_sound(self):
        """Instant startup greeting from pre-rendered local audio file."""
        ready_file = BASE_DIR / "data" / "sounds" / "ready.mp3"
        if ready_file.exists():
            print(f"⚡ [INSTANT] Playing pre-generated startup greeting...")
            self.player.play_url_or_file(str(ready_file), is_speech=True)
        else:
            self.speak("Radhe Radhe! RK AI Assistant is ready.")

    def speak(self, text: str):
        """Play TTS audio with automatic whisper/night mode adjustment."""
        if not text:
            return

        # Play answer transition earcon cleanly before speech starts
        self.player.play_chime("answer", sync=True)

        if self.conversation.is_whisper_mode_active():
            print("🌙 [NIGHT PROTOCOL] Volume lowered to 30% for gentle playback.")
            self.player.set_system_volume("set", 30)

        # Gate sound monitor while TTS is speaking
        if hasattr(self, "sound_monitor"):
            self.sound_monitor.tts_active = True

        print(f"🗣️ [TTS] {text}")
        audio_file = self.tts.get_speech_file(text)
        if audio_file:
            self.player.play_url_or_file(audio_file, is_speech=True)
            # Block until playback completes so the mic loop doesn't hear or interrupt the assistant's own voice
            self.player.wait_playback(timeout=15.0)

        if hasattr(self, "sound_monitor"):
            self.sound_monitor.tts_active = False

    def listen_and_process_voice(self):
        """
        Record voice input from microphone, verify transcribed text,
        and execute command through the single-turn loop.
        """
        # If mic is hardware-muted, skip the entire listen cycle and sleep silently
        if self.recorder.is_hardware_muted:
            if not getattr(self, "_muted_logged", False):
                print("🔇 [MIC] AI Muted — voice listening paused.", flush=True)
                self._muted_logged = True
            time.sleep(1.0)
            return

        if getattr(self, "_muted_logged", False):
            print("🎙️ [MIC] AI Unmuted — voice listening resumed.", flush=True)
            self._muted_logged = False

        # ── Ambient listen ───────────────────────────────────────────────────
        if self.player.is_playing():
            self.player.duck_for_voice()
        print("👂 [LISTENING]...", end="\r", flush=True)
        wav_path = self.recorder.record_command(duration=10, silence_duration=1.2)
        if self.player._is_ducked:
            self.player.unduck_audio()

        if not wav_path:
            # Silence — loop continues silently
            return

        print("\n⚡ [AUDIO] Processing speech...", flush=True)

        # ── Speech detected — check for background events first ─────────────
        self.sound_monitor.check_audio_file(wav_path)

        # ── Transcribe ───────────────────────────────────────────────────────
        text = self.recorder.transcribe(client=self.client)

        if not text:
            print("⚠️ [STT] Audio was unclear or noise.", flush=True)
            return

        # ── Wake-word gate: only act if "rk" appears anywhere in the sentence ──
        import re
        words = re.findall(r"\b\w+\b", text.lower())
        if "rk" not in words:
            print(f"🔕 [WAKE] Ignored (no wake-word 'RK'): '{text}'", flush=True)
            return

        # Strip the wake-word "rk" from command before sending to handler
        clean_text = re.sub(r"\brk\b", "", text, flags=re.IGNORECASE).strip(" ,.-")
        clean_text = re.sub(r"\s{2,}", " ", clean_text).strip()

        # ── Real command detected — NOW play earcons ─────────────────────────
        print(f"✅ [COMMAND] '{clean_text}' (from: '{text}')", flush=True)
        self.player.play_chime("captured", sync=True)
        self.player.play_chime("thinking")

        self.handle_command(clean_text if clean_text else text)

    def handle_command(self, query: str):
        """
        Alexa-Grade Single-Turn Execution Loop:
        1. Context Stacking & pronoun resolution ('there', 'play like this')
        2. Active Interactive Mode (Quiz Q&A)
        3. Fast Instant Router (<0.5ms local execution)
        4. RK_AI_HOME Backend Dispatch (Cloud intelligence)
        """
        import re
        query = query.strip()
        if not query:
            return

        # Strip wake-word prefix/suffix if present (e.g. from text commands: "rk what is the time")
        stripped_query = re.sub(r"\brk\b", "", query, flags=re.IGNORECASE).strip(" ,.-")
        stripped_query = re.sub(r"\s{2,}", " ", stripped_query).strip()
        active_query = stripped_query if stripped_query else query

        # 4.1 Resolve Contextual Pronouns
        resolved_query = self.conversation.resolve_contextual_query(active_query)
        print(f"\n⚡ [EXECUTING] '{resolved_query}'")

        # ─── ACTIVE MODE: QUIZ ANSWERING ───────────────
        if self.quiz.is_active:
            if resolved_query.lower() in ("cancel quiz", "stop quiz", "exit quiz"):
                self.quiz.cancel_quiz()
                return
            handled = self.quiz.submit_answer(resolved_query)
            if handled:
                return

        # ─── STEP 1: FAST INSTANT ROUTER ───────────────
        matched, local_res = FastCommandRouter.route(resolved_query)
        if matched and local_res:
            print(f"⚡ [Instant Match] {local_res}")
            tool = local_res.get("tool")
            args = local_res.get("args", {})

            if tool == "diagnostics":
                report = SystemDiagnostics.get_spoken_report()
                self.speak(report)
                self.conversation.add_interaction(resolved_query, report, tool)
                return

            elif tool == "benchmark":
                self.speak("Running developer benchmark now.")
                from core.developer_mode import BenchmarkSuite
                suite = BenchmarkSuite()
                suite.run_all()
                self.conversation.add_interaction(resolved_query, "Benchmark complete", tool)
                return

            elif tool == "morning_routine":
                briefing = self.conversation.execute_morning_routine()
                self.speak(briefing)
                self.conversation.add_interaction(resolved_query, briefing, tool)
                return

            elif tool == "find_phone":
                self.remote_sync.trigger_ring_phone()
                self.conversation.add_interaction(resolved_query, "Ringing phone", tool)
                return

            elif tool == "emergency_sos":
                self.remote_sync.trigger_sos_alarm()
                self.conversation.add_interaction(resolved_query, "Emergency SOS triggered", tool)
                return

            elif tool == "weather":
                city = args.get("city", "Delhi")
                weather_text = WeatherService.get_spoken_weather(city)
                self.speak(weather_text)
                self.conversation.add_interaction(resolved_query, weather_text, tool)
                return

            elif tool == "routine":
                routine_name = args.get("routine", "")
                self.automation.execute_routine(routine_name)
                self.conversation.add_interaction(resolved_query, f"Started {routine_name}", tool)
                return

            reply = local_res.get("reply", "")
            if reply:
                self.speak(reply)

            self._execute_local_action(tool, args)
            self.conversation.add_interaction(resolved_query, reply, tool)
            return

        # ─── STEP 2: RK_AI_HOME BACKEND CALL ───────────
        print(f"☁️ [Backend] Forwarding to RK_AI_HOME...")
        self.player.play_chime("thinking")
        backend_res = self.client.send_text(resolved_query)

        reply = backend_res.get("reply") if backend_res else None

        # ─── STEP 3: OFFLINE LLM FALLBACK ───────────────
        # Kicks in automatically when cloud backend is asleep, slow, or unreachable
        if not reply and self.offline_llm.is_ready:
            print("📡 [Fallback] Cloud backend timed out or unreachable — answering via local Qwen2.5 LLM...")
            self.player.play_chime("thinking")
            self.speak("Cloud backend is taking a moment, let me think locally.")
            reply = self.offline_llm.ask(resolved_query)
            if reply:
                self.speak(reply)
            else:
                self.speak("Sorry, I couldn't answer that offline either.")
            self.conversation.add_interaction(resolved_query, reply or "", "offline_llm")
            return

        if reply:
            self.speak(reply)

        # ─── Execute physical hardware actions from backend response ────────
        backend_intent = backend_res.get("intent") if backend_res else None
        backend_params = {}
        if backend_res and isinstance(backend_res.get("intents"), list) and len(backend_res["intents"]) > 0:
            backend_params = backend_res["intents"][0].get("parameters", {})

        # Map backend cloud intents directly to local hardware triggers
        if backend_intent == "period_bell":
            self.alarm_mgr.ring_period_bell(backend_params.get("label", "Period Bell"))
        elif backend_intent in ("emergency_alarm", "fire_alarm"):
            self.remote_sync.trigger_sos_alarm()
        elif backend_intent == "stop_alarm":
            self.alarm_mgr.stop_alarm()
        elif backend_intent == "shutdown":
            self._execute_local_action("system", {"action": "shutdown"})
        elif backend_intent == "alarm":
            self._execute_local_action("alarm", {"action": "set", "time": backend_params.get("time")})

        local_action = backend_res.get("local_action") if backend_res else None
        if local_action:
            tool = local_action.get("tool")
            args = local_action.get("args", {})
            self._execute_local_action(tool, args)

        self.conversation.add_interaction(resolved_query, reply or "", local_action.get("tool") if local_action else (backend_intent or "chat"))

    def _execute_local_action(self, tool: str, args: dict):
        """Dispatches actual local actions on Pi hardware."""
        if tool == "volume":
            self.player.set_system_volume(
                action=args.get("action", "set"),
                level=args.get("level"),
                step=args.get("step", 10)
            )

        elif tool == "playback_control":
            if args.get("action") == "stop":
                self.player.stop()

        elif tool == "alarm":
            action = args.get("action")
            if action == "set":
                self.alarm_mgr.set_alarm(
                    time_str=args.get("time"),
                    label=args.get("label", "Alarm"),
                    days=args.get("days"),
                    wake_up_message=args.get("wake_up_message", "")
                )
            elif action == "stop":
                self.alarm_mgr.stop_alarm()

        elif tool == "period_bell":
            self.alarm_mgr.ring_period_bell(args.get("label", "Period Bell"))

        elif tool == "pomodoro":
            act = args.get("action")
            if act == "start":
                self.pomodoro.start(study_minutes=args.get("minutes", 25))
            elif act == "stop":
                self.pomodoro.stop()

        elif tool == "quiz":
            act = args.get("action")
            if act == "start":
                self.quiz.start_quiz(topic=args.get("topic", "General Knowledge"))
            elif act == "stop":
                self.quiz.cancel_quiz()

        elif tool == "note":
            self.conversation.save_voice_note(args.get("content", ""))

        elif tool == "hardware_mic":
            act = args.get("action")
            if act == "mute":
                HardwareMicManager.mute()
                self.recorder.is_hardware_muted = True
            elif act == "unmute":
                HardwareMicManager.unmute()
                self.recorder.is_hardware_muted = False

        elif tool == "night_mode_toggle":
            enabled = args.get("enabled", True)
            self.conversation.set_night_mode(enabled)

        elif tool == "music":
            song_url = args.get("song_url")
            q = args.get("query", "")
            
            # 1. Spotify Check (If connected, stream via Spotify)
            if self.spotify.is_connected:
                print(f"🎵 [Music] Routing '{q}' through Spotify...")
                ok = self.spotify.play_track_or_query(q, streamer=LocalMusicStreamer, player=self.player)
                if ok:
                    return

            # 2. If we already have a stream URL, play it
            if song_url:
                print(f"🎵 [Music] Streaming direct: {song_url}")
                self.player.play_url_or_file(song_url)
                return

            # 3. LOCAL RESOLUTION FIRST (Instant, doesn't need backend!)
            print(f"🎵 [Music] Resolving locally via yt-dlp: '{q}'...")
            local_stream = LocalMusicStreamer.get_audio_stream_url(q)
            if local_stream:
                print(f"🎵 [Music] Streaming local audio...")
                self.player.play_url_or_file(local_stream)
                return

            # 4. Fallback to backend if yt-dlp local resolution fails
            print(f"🎵 [Music] Fallback to backend for: {q}")
            res = self.client.send_text(f"play {q}")
            local_action = res.get("local_action") or {}
            b_url = local_action.get("args", {}).get("song_url") if isinstance(local_action, dict) else None
            if b_url:
                self.player.play_url_or_file(b_url)

        elif tool == "system":
            act = args.get("action")
            if act == "reboot":
                os.system("sudo reboot")
            elif act == "shutdown":
                os.system("sudo poweroff")

    def _background_worker(self):
        """
        Dedicated daemon thread — runs every second, never blocks the voice loop.
        Responsibilities:
          • 5s  — Alarm/Pomodoro ticks
          • 5s  — Remote command polling (mobile app / web dashboard → Pi)
          • 5s  — Speaker keepalive (prevents BT audio from sleeping)
          • 30s — Heartbeat ping (backend knows device is online)
          • 60s — Maintenance poll (device limits / config sync)
          • 60s — Bluetooth adapter health check
        """
        import threading
        last_heartbeat   = 0.0
        last_maintenance = 0.0

        print("🔁 [Worker] Background thread started.")
        while not self._stop_worker.is_set():
            now = time.time()
            try:
                # Fast ticks (every loop iteration, internal rate-limiting inside each)
                self.alarm_mgr.check_alarms_tick()
                self.pomodoro.tick()
                self.player.send_speaker_keepalive()
                self.remote_sync.poll_remote_commands()

                # 30s heartbeat — lets backend know Pi is alive
                if now - last_heartbeat > 30:
                    last_heartbeat = now
                    self.client.ping_alive()

                # 60s maintenance + BT check + settings sync
                if now - last_maintenance > 60:
                    last_maintenance = now
                    BluetoothAdapterManager.verify_or_reboot()
                    settings = self.client.poll_maintenance()
                    if settings and isinstance(settings, dict):
                        tts_conf = settings.get("ttsConfig")
                        if tts_conf and hasattr(self.tts, "set_config"):
                            self.tts.set_config(tts_conf)
                        # Note: We do NOT force backend's default volume here every 60s
                        # so that user volume changes via commands / local persistence aren't clobbered!

            except Exception as e:
                print(f"⚠️ [Worker] Error: {e}")

            self._stop_worker.wait(timeout=1.0)

        print("🛑 [Worker] Background thread stopped.")

    def run_voice_loop(self):
        """
        Continuous hands-free voice loop — the only way to talk to RK AI.
        Listens immediately after each response finishes.
        """
        import threading
        # 1. Background worker for heartbeat, alarms & commands
        self._stop_worker = threading.Event()
        worker = threading.Thread(target=self._background_worker, daemon=True)
        worker.start()

        # 2. One-time mic calibration while system is completely silent
        self.recorder.calibrate_once()

        # 3. Startup greeting (AFTER calibration & background setup)
        # Skip if emergency alarm is already ringing
        if not getattr(self.player, "_is_emergency", False):
            self.play_ready_sound()
            self.player.wait_playback(timeout=8.0)

        print("\n🎙️ [VOICE MODE] System fully initialized — listening continuously!", flush=True)
        try:
            while True:
                self.listen_and_process_voice()
        except KeyboardInterrupt:
            print("\n👋 Shutting down RK AI Assistant.")
        finally:
            self._stop_worker.set()
            worker.join(timeout=3)

if __name__ == "__main__":
    assistant = RKV2Assistant()
    assistant.run_voice_loop()


