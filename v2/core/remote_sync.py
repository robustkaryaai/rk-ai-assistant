import time
import shutil
import threading
import subprocess as sp
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
        """5.4 Emergency SOS Fire Brigade Siren & Evacuation Alert with Real-time Ducking."""
        print("🚨 [SOS] Emergency fire / panic alarm triggered!")
        from pathlib import Path
        sounds_dir = Path(__file__).resolve().parent.parent / "data" / "sounds"
        sos_evacuate_file = sounds_dir / "sos_evacuate.mp3"
        fire_alarm_file = sounds_dir / "fire_alarm.mp3"
        siren_file = sounds_dir / "emergency_siren.wav"

        # Flag emergency in player so volume ducking and startup sounds never preempt it
        if self.player:
            self.player._is_emergency = True
            self.player.set_system_volume("set", 100)

        # 1. Preferred: High-fidelity seamless ducked evacuation mix (Siren -> Ducks to 20% -> TTS plays loud -> Siren resumes full blast)
        if sos_evacuate_file.exists() and self.player:
            print("🔊 [SOS] Playing ducked emergency siren & evacuation broadcast...", flush=True)
            self.player.play_url_or_file(str(sos_evacuate_file))
            return

        # 2. Dynamic Fallback: Play siren briefly, duck volume, announce evacuation, resume full volume
        if self.player and (fire_alarm_file.exists() or siren_file.exists()):
            target = str(fire_alarm_file) if fire_alarm_file.exists() else str(siren_file)
            print("🔊 [SOS] Playing intro siren...", flush=True)
            self.player.play_url_or_file(target)
            time.sleep(2.5)  # Let siren scream for 2.5s

            # Duck volume for voice announcement
            print("🔊 [SOS] Ducking siren for emergency voice broadcast...", flush=True)
            self.player.set_system_volume("set", 30)
            if self.tts:
                self.tts.speak("Emergency fire alarm triggered! Please evacuate immediately.")
            time.sleep(4.0)

            # Bring volume back to 100% continuous alarm
            print("🔊 [SOS] Restoring siren to 100%...", flush=True)
            self.player.set_system_volume("set", 100)
            self.player.play_url_or_file(target)
        elif self.tts:
            self.tts.speak("Emergency fire alarm triggered! Please evacuate immediately.")

    def poll_remote_commands(self):
        """
        5.2 Polls pending commands sent from the mobile/web dashboard.
        Optimized to poll every 1-2 seconds with persistent HTTP session.
        """
        now = time.time()
        # If music is resolving or playing, back off polling to 10s to give 100% CPU and network to yt-dlp
        is_busy = getattr(self.assistant, "_music_resolving", False) or (self.player and self.player.is_playing())
        poll_interval = 10.0 if is_busy else 3.5
        if now - self._last_cmd_poll < poll_interval:
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
        except Exception:
            pass

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
            elif action in ("mute_mic", "mute", "unmute"):
                mute_state = False if action == "unmute" else payload.get("mute", True)
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
                    is_youtube = "youtube.com" in url or "youtu.be" in url
                    if is_youtube:
                        # Run yt-dlp in background so voice loop is never blocked
                        def _resolve_and_play(yt_url):
                            print(f"🎵 [MUSIC] Resolving YouTube stream in background...", flush=True)
                            stream_url = None
                            if shutil.which("yt-dlp"):
                                try:
                                    cmd = [
                                        "yt-dlp",
                                        "-f", "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
                                        "-g",
                                        "--no-playlist",
                                        "--no-warnings",
                                        "--geo-bypass",
                                        "--socket-timeout", "10",
                                        "--extractor-retries", "3",
                                        yt_url,
                                    ]
                                    res = sp.run(cmd, stdout=sp.PIPE, stderr=sp.PIPE, text=True, timeout=45)
                                    for line in res.stdout.strip().splitlines():
                                        line = line.strip()
                                        if line.startswith("http"):
                                            stream_url = line
                                            break
                                    if not stream_url and res.stderr:
                                        print(f"⚠️ [MUSIC] yt-dlp: {res.stderr.strip()[:150]}", flush=True)
                                except Exception as e:
                                    print(f"⚠️ [MUSIC] yt-dlp failed: {e}", flush=True)
                            if stream_url:
                                print(f"✅ [MUSIC] Stream ready — playing now.", flush=True)
                                self.player.play_url_or_file(stream_url)
                            else:
                                print(f"⚠️ [MUSIC] Falling back to direct YouTube URL.", flush=True)
                                self.player.play_url_or_file(yt_url)

                        t = threading.Thread(target=_resolve_and_play, args=(url,), daemon=True)
                        t.start()
                        result = "Resolving and playing music in background"
                    else:
                        # Non-YouTube CDN URL (Saavn etc.) — play instantly, no extraction needed
                        self.player.play_url_or_file(url)
                        result = "Playing music"
            elif action == "stop":
                self.player.stop()
            elif action == "volume":
                # Backend sends {"volume": 40}, not {"level": 40}
                level = int(payload.get("volume") or payload.get("level") or 70)
                # Set volume silently without interrupting playing music
                self.player.set_system_volume("set", level, play_chime=False)
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
            elif action == "set_tts_config":
                if hasattr(self.assistant, "tts") and hasattr(self.assistant.tts, "set_config"):
                    self.assistant.tts.set_config(payload)
                result = f"TTS Config updated: {payload}"
                print(f"🗣️ [REMOTE] set_tts_config: {payload}", flush=True)
            elif action == "delete_alarm":
                alarm_id = payload.get("alarm_id") or payload.get("id")
                deleted = self.assistant.alarm_mgr.delete_alarm(str(alarm_id))
                result = f"Alarm {alarm_id} deleted: {deleted}"
                print(f"🗑️ [REMOTE] delete_alarm: {alarm_id} -> {result}", flush=True)
            elif action == "delete_schedule":
                sched_id = payload.get("schedule_id") or payload.get("id")
                deleted = self.assistant.alarm_mgr.delete_schedule(str(sched_id))
                result = f"Schedule {sched_id} deleted: {deleted}"
                print(f"🗑️ [REMOTE] delete_schedule: {sched_id} -> {result}", flush=True)
            elif action == "set_alarm":
                time_str = payload.get("time", "")
                label = payload.get("label", "Alarm")
                days = payload.get("days", [])
                alarm = self.assistant.alarm_mgr.set_alarm(time_str=time_str, label=label, days=days)
                result = f"Alarm set: {alarm}"
                print(f"⏰ [REMOTE] set_alarm: {alarm}", flush=True)
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



