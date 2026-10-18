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
    MAINTENANCE_POLL_INTERVAL
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

class RKV2Assistant:
    def __init__(self):
        print("==================================================")
        print("🚀 RK AI Assistant V2 (Pi Zero W / 512MB RAM)")
        print(f"📍 Device Slug:  {DEVICE_SLUG}")
        print(f"📶 BT Adapter:   {BLUETOOTH_HCI} (Strict)")
        print(f"🔊 Speaker MAC:  {BLUETOOTH_SPEAKER_MAC}")
        print(f"🌐 Backend Host: {BACKEND_BASE_URL}")
        print("==================================================")

        # 1. Hardware Pinning & Watchdog (Strict hci1)
        BluetoothAdapterManager.verify_or_reboot()

        # 2. Audio & Backend Subsystems
        self.player = AudioPlayer()
        self.tts = TTSManager(AUDIO_CACHE_DIR)
        self.client = RKHomeClient(BACKEND_BASE_URL, DEVICE_SLUG)

        # 3. Core Engines
        self.data_dir = BASE_DIR / "data"
        self.recorder = AudioRecorder(self.data_dir)
        self.alarm_mgr = AlarmScheduleManager(self.data_dir, client=self.client, player=self.player, tts=self)
        self.pomodoro = PomodoroTimer(self.alarm_mgr, tts=self)
        self.quiz = VoiceQuizEngine(tts=self)
        self.conversation = ConversationEngine(client=self.client, tts=self, player=self.player)
        self.remote_sync = RemoteSyncManager(client=self.client, assistant=self, player=self.player, tts=self)

        self._last_maintenance = 0.0

    def speak(self, text: str):
        """Play TTS audio with automatic whisper/night mode adjustment."""
        if not text:
            return

        if self.conversation.is_whisper_mode_active():
            print("🌙 [NIGHT MODE] Volume lowered to 25% for gentle playback.")
            self.player.set_system_volume("set", 25)

        print(f"🗣️ [TTS] {text}")
        audio_file = self.tts.get_speech_file(text)
        if audio_file:
            self.player.play_url_or_file(audio_file, is_speech=True)

    def listen_and_process_voice(self):
        """
        Record voice input from microphone, verify transcribed text,
        and execute command through the single-turn loop.
        """
        self.player.duck_for_voice()
        self.player.play_chime("wake")
        print("\n🎤 [LISTENING] Speak your command...")

        wav_path = self.recorder.record_command(duration=5)
        self.player.unduck_audio()

        if not wav_path:
            print("⚠️ [MIC] No audio captured or silence.")
            return

        print("🔍 [STT] Verifying and transcribing speech...")
        self.player.play_chime("thinking")
        text = self.recorder.transcribe(client=self.client)

        if not text:
            print("⚠️ [STT] Could not recognize speech.")
            return

        print(f"✅ [VERIFIED INPUT] '{text}'")
        self.handle_command(text)

    def handle_command(self, query: str):
        """
        Alexa-Grade Single-Turn Execution Loop:
        1. Context Stacking & pronoun resolution ('there', 'play like this')
        2. Active Interactive Mode (Quiz Q&A)
        3. Fast Instant Router (<0.5ms local execution)
        4. RK_AI_HOME Backend Dispatch (Cloud intelligence)
        """
        query = query.strip()
        if not query:
            return

        # 4.1 Resolve Contextual Pronouns
        resolved_query = self.conversation.resolve_contextual_query(query)
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

            reply = local_res.get("reply", "")
            if reply:
                self.speak(reply)

            self._execute_local_action(tool, args)
            self.conversation.add_interaction(resolved_query, reply, tool)
            return

        # ─── STEP 2: RK_AI_HOME BACKEND CALL ───────────
        print(f"☁️ [Backend] Forwarding to RK_AI_HOME...")
        backend_res = self.client.send_text(resolved_query)

        reply = backend_res.get("reply")
        if reply:
            self.speak(reply)

        local_action = backend_res.get("local_action")
        if local_action:
            tool = local_action.get("tool")
            args = local_action.get("args", {})
            self._execute_local_action(tool, args)

        self.conversation.add_interaction(resolved_query, reply, local_action.get("tool") if local_action else "chat")

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

        elif tool == "music":
            song_url = args.get("song_url")
            q = args.get("query", "")
            
            # 1. If we already have a stream URL, play it
            if song_url:
                print(f"🎵 [Music] Streaming direct: {song_url}")
                self.player.play_url_or_file(song_url)
                return

            # 2. LOCAL RESOLUTION FIRST (Instant, doesn't need backend!)
            print(f"🎵 [Music] Resolving locally via yt-dlp: '{q}'...")
            local_stream = LocalMusicStreamer.get_audio_stream_url(q)
            if local_stream:
                print(f"🎵 [Music] Streaming local yt-dlp URL...")
                self.player.play_url_or_file(local_stream)
                return

            # 3. Fallback to backend if yt-dlp local resolution fails
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

    def run_tick(self):
        """Cooperative single-loop tick."""
        self.alarm_mgr.check_alarms_tick()
        self.pomodoro.tick()
        self.player.send_speaker_keepalive()
        self.remote_sync.poll_remote_commands()

        now = time.time()
        if now - self._last_maintenance > MAINTENANCE_POLL_INTERVAL:
            self._last_maintenance = now
            BluetoothAdapterManager.verify_or_reboot()
            self.client.poll_maintenance()

if __name__ == "__main__":
    assistant = RKV2Assistant()
    assistant.speak("Radhe Radhe! RK AI Assistant V2 is ready.")

    print("\n[READY] Options:")
    print("  • Press [ENTER] to record voice from microphone")
    print("  • Or type text command directly")
    print("  • Press Ctrl+C to exit")

    try:
        while True:
            assistant.run_tick()
            try:
                cmd = input("\n[Mic: ENTER / Text: Type] > ")
                if not cmd.strip():
                    assistant.listen_and_process_voice()
                else:
                    assistant.handle_command(cmd)
            except EOFError:
                break
    except KeyboardInterrupt:
        print("\nShutting down V2 Assistant.")
