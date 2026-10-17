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
        """5.4 Emergency SOS Siren & Contact Alert."""
        print("🚨 [SOS] Emergency panic alarm triggered!")
        # Sound alarm at high volume
        self.player.set_system_volume("set", 100)
        self.tts.speak("Emergency SOS triggered. Alerting contacts.")
        if self.client:
            self.client.send_text("emergency_alarm_trigger")

    def poll_remote_commands(self):
        """
        5.2 Polls pending commands sent from the mobile/web dashboard.
        Endpoints: GET /device/:slug/commands/pending
                   POST /device/:slug/commands/:command_id/complete
        """
        now = time.time()
        if now - self._last_cmd_poll < 5: # Poll every 5s
            return
        self._last_cmd_poll = now

        if not self.client:
            return

        try:
            url = f"{self.client.base_url}/device/{self.client.slug}/commands/pending"
            resp = self.client.session.get(url, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                commands = data.get("commands", [])
                for cmd in commands:
                    self._execute_remote_command(cmd)
        except Exception:
            pass

    def _execute_remote_command(self, cmd: Dict[str, Any]):
        cmd_id = cmd.get("id") or cmd.get("$id")
        action = cmd.get("action")
        payload = cmd.get("payload", {})

        print(f"📥 [REMOTE COMMAND] Received: {action} ({cmd_id})")

        success = True
        result = "Executed"

        try:
            if action == "speak":
                text = payload.get("text", "")
                self.tts.speak(text)
            elif action == "play_music":
                url = payload.get("url")
                if url:
                    self.player.play_url_or_file(url)
            elif action == "stop":
                self.player.stop()
            elif action == "volume":
                level = int(payload.get("level", 70))
                self.player.set_system_volume("set", level)
            elif action == "ring_alarm":
                self.assistant.alarm_mgr.ring_period_bell("Remote Ring")
        except Exception as e:
            success = False
            result = str(e)

        # Acknowledge command completion to backend
        if cmd_id and self.client:
            try:
                complete_url = f"{self.client.base_url}/device/{self.client.slug}/commands/{cmd_id}/complete"
                self.client.session.post(complete_url, json={"success": success, "result": result}, timeout=3)
            except Exception:
                pass
