import time
from typing import Dict, Any, List

class RemoteSyncManager:
    """
    Section 5: Phone & IoT Integration Manager
    - 5.1 "Find My Phone / Ring My Device" voice dispatch
    - 5.2 Remote Cloud Command Poller (Mobile App control via /device/:slug/commands/pending)
    - 5.3 Intercom & Voice Broadcasts
    - 5.4 Emergency SOS Siren
    - 5.5 Auto-Recovery Wi-Fi Watchdog
    """

    def __init__(self, client, assistant, player, tts):
        self.client = client
        self.assistant = assistant
        self.player = player
        self.tts = tts
        self._last_cmd_poll = 0.0

    def trigger_ring_phone(self):
        """5.1 Voice trigger: 'Where is my phone?' / 'Ring my phone'."""
        print("📱 [REMOTE] Triggering high-priority phone ring...")
        if self.client:
            self.client.send_text("find_my_phone_trigger")
        self.tts.speak("Pinging your phone now at maximum volume.")

    def trigger_sos_alarm(self):
        """5.4 Emergency SOS Fire Brigade Siren & Contact Alert."""
        print("🚨 [SOS] Emergency fire / panic alarm triggered!")
        from pathlib import Path
        sounds_dir = Path(__file__).resolve().parent.parent / "data" / "sounds"
        fire_alarm_file = sounds_dir / "fire_alarm.mp3"
        siren_file = sounds_dir / "emergency_siren.wav"

        # Max out volume and blast fire brigade alarm
        if self.player:
            self.player.set_system_volume("set", 100)
            if fire_alarm_file.exists():
                self.player.play_url_or_file(str(fire_alarm_file))
            elif siren_file.exists():
                self.player.play_url_or_file(str(siren_file), sync=True)

        if self.tts:
            self.tts.speak("Emergency fire alarm triggered! Please evacuate immediately.")
        if self.client:
            self.client.send_text("emergency_alarm_trigger")

    def poll_remote_commands(self):
        """
        5.2 Polls pending commands sent from the mobile/web dashboard.
        Called from the background worker thread every ~5 seconds.
        """
        now = time.time()
        if now - self._last_cmd_poll < 15:   # Pi Zero W: poll every 15s to save CPU
            return
        self._last_cmd_poll = now

        if not self.client:
            return

        try:
            commands = self.client.fetch_pending_commands()
            if commands:
                print(f"📥 [REMOTE] {len(commands)} pending command(s) received.", flush=True)
            for cmd in commands:
                self._execute_remote_command(cmd)
        except Exception as e:
            print(f"⚠️ [REMOTE] poll_remote_commands error: {e}", flush=True)

    def _execute_remote_command(self, cmd: Dict[str, Any]):
        cmd_id = cmd.get("$id") or cmd.get("id")

        # Backend uses "commandType" — not "action"
        action = cmd.get("commandType") or cmd.get("action") or cmd.get("type")

        # Payload field is correct
        payload = cmd.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        print(f"📥 [REMOTE COMMAND] Received: '{action}' (id={cmd_id})", flush=True)

        success = True
        result = "Executed"

        try:
            if action == "speak":
                text = payload.get("text", "")
                self.tts.speak(text)
            elif action == "set_custom_greeting":
                greeting_text = payload.get("greeting", "Radhe Radhe! RK AI Assistant is ready.")
                print(f"🎙️ [REMOTE] Updating custom startup greeting: '{greeting_text}'")
                try:
                    from gtts import gTTS
                    from config import BASE_DIR
                    ready_path = BASE_DIR / "data" / "sounds" / "ready.mp3"
                    ready_path.parent.mkdir(parents=True, exist_ok=True)
                    tts_inst = gTTS(text=greeting_text, lang="en", tld="co.in")
                    tts_inst.save(str(ready_path))
                    result = "Custom greeting generated and saved"
                except Exception as ge:
                    result = f"Failed to pre-render greeting: {ge}"
            elif action == "toggle_download_mode":
                enable = payload.get("enabled", False)
                from audio.streamer import LocalMusicStreamer
                LocalMusicStreamer.set_download_mode(enable)
                result = f"Download mode set to {enable}"
            elif action == "set_spotify_token":
                token = payload.get("token", "")
                if hasattr(self.assistant, "spotify"):
                    self.assistant.spotify.set_token(token)
                result = "Spotify token configured"
            elif action == "mute_mic":
                mute_state = payload.get("mute", True)
                from hardware.mic import HardwareMicManager
                HardwareMicManager.set_mute(mute_state)
                self.assistant.recorder.is_hardware_muted = mute_state
                result = f"Hardware mic mute set to {mute_state}"
            elif action == "toggle_night_protocol":
                night_state = payload.get("enabled", True)
                self.assistant.conversation.set_night_mode(night_state)
                result = f"Night protocol set to {night_state}"
            elif action == "play_music":
                url = payload.get("url")
                if url:
                    self.player.play_url_or_file(url)
            elif action == "stop":
                self.player.stop()
            elif action == "volume":
                # Backend sends {"volume": 40}, not {"level": 40}
                level = int(payload.get("volume") or payload.get("level") or 70)
                self.player.set_system_volume("set", level)
                result = f"Volume set to {level}%"
                print(f"🔊 [REMOTE] Volume set to {level}%", flush=True)
            elif action == "text_command":
                # Text command typed from mobile app / web dashboard —
                # runs through the exact same pipeline as a voice command
                text = payload.get("text") or payload.get("command") or payload.get("query", "")
                # Acknowledge immediately before running so Appwrite doesn't think command is stuck
                if cmd_id and self.client:
                    self.client.ack_command(cmd_id, True, "Acknowledged")
                cmd_id = None # Avoid double acking below

                if text:
                    print(f"💬 [REMOTE] Text command: '{text}'", flush=True)
                    self.assistant.handle_command(text)
                    result = f"Executed: '{text}'"
                else:
                    result = "text_command received but payload had no text"
            elif action == "ring_alarm":
                self.assistant.alarm_mgr.ring_period_bell("Remote Ring")
            else:
                result = f"Unknown commandType: '{action}'"
                print(f"⚠️ [REMOTE] Unknown command: '{action}'", flush=True)
        except Exception as e:
            success = False
            result = str(e)
            print(f"❌ [REMOTE COMMAND] Error executing '{action}': {e}", flush=True)

        # Acknowledge command completion to backend
        if cmd_id and self.client:
            self.client.ack_command(cmd_id, success, result)



