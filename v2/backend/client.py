import os
import requests
from typing import Optional, Dict, Any, List

class RKHomeClient:
    """
    Lightweight HTTP Gateway to RK_AI_HOME Backend.
    - Zero local ML / Zero local Gemini SDK overhead on Pi.
    - Backend executes heavy tools (images, video, docx, ppt, storage, teacher tools).
    - Returns clean spoken text + only local Pi tasks (music audio streams, alarms, period bell).
    """

    def __init__(self, base_url: str, slug: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.slug = slug
        self.timeout = timeout
        self.session = requests.Session()
        self._ensure_device_registered()

    def _ensure_device_registered(self):
        """Auto-registers device slug with backend on boot if not already present."""
        if not self.slug or self.slug == "000000000":
            return
        try:
            url = f"{self.base_url}/device/ensure/{self.slug}"
            self.session.post(url, timeout=5)
        except Exception:
            pass

    def send_text(self, text: str) -> Dict[str, Any]:
        """
        Send user voice transcript or text query to RK_AI_HOME.
        Retries up to 3 times on timeout or transient network failure.
        """
        url = f"{self.base_url}/text/{self.slug}"
        payload = {"text": text}
        max_attempts = 3
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                resp = self.session.post(url, json=payload, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                return self._parse_backend_response(data)
            except Exception as e:
                last_error = e
                print(f"[backend] Attempt {attempt}/{max_attempts} failed: {e}")
                if attempt < max_attempts:
                    import time
                    time.sleep(1.5)

        print(f"[backend] All {max_attempts} connection attempts failed: {last_error}")
        return {
            "reply": None,
            "local_action": None,
            "shoom": False,
            "error": str(last_error)
        }

    def _parse_backend_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Strips cloud generation tasks (already executed on backend)
        and extracts only local hardware actions for the Pi.
        Supports both modern {reply, intents} and legacy {message, intent, text} formats.
        """
        print(f"[backend] Raw response received: {data}")

        # Extract reply text from various possible fields
        reply = data.get("reply") or data.get("message") or data.get("response") or data.get("text") or ""
        
        # Normalize intents
        intents: List[Dict[str, Any]] = []
        if "intents" in data and isinstance(data["intents"], list):
            intents = data["intents"]
        elif "intent" in data:
            if isinstance(data["intent"], str):
                intents = [{"intent": data["intent"], "parameters": data.get("parameters", {})}]
            elif isinstance(data["intent"], list):
                intents = data["intent"]
            elif isinstance(data["intent"], dict):
                intents = [data["intent"]]

        # If reply is empty, check if intent itself contains the reply
        if not reply:
            for item in intents:
                p = item.get("parameters", {})
                if isinstance(p, dict):
                    possible_reply = p.get("reply") or p.get("message") or p.get("response")
                    if possible_reply:
                        reply = possible_reply
                        break

        song_url = data.get("song_url") or data.get("link")
        
        local_action = None

        # Check for local Pi tools: music, alarm, period_bell
        for item in intents:
            intent_name = item.get("intent")
            params = item.get("parameters", {})

            if intent_name == "music":
                local_action = {
                    "tool": "music",
                    "args": {
                        "song_url": song_url or params.get("song_url"),
                        "query": params.get("prompt", "music")
                    }
                }
                break

            elif intent_name in ("set_alarm", "alarm"):
                local_action = {
                    "tool": "alarm",
                    "args": {
                        "action": "set",
                        "time": params.get("time"),
                        "label": params.get("label", "Alarm"),
                        "wake_up_message": params.get("wakeUpMessage")
                    }
                }
                break

            elif intent_name in ("stop_alarm", "delete_alarm"):
                local_action = {
                    "tool": "alarm",
                    "args": {"action": "stop"}
                }
                break

            elif intent_name == "period_bell":
                local_action = {
                    "tool": "period_bell",
                    "args": params
                }
                break

        return {
            "reply": reply,
            "local_action": local_action
        }

    def send_audio(self, audio_bytes: bytes) -> Dict[str, Any]:
        """
        Transcribes voice audio via backend Whisper STT (/audio/:slug).
        """
        import base64
        url = f"{self.base_url}/audio/{self.slug}"
        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        try:
            resp = self.session.post(url, json={"audio": b64_audio}, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def ping_alive(self) -> bool:
        """
        Lightweight heartbeat — lets the backend know the device is online.
        POST /device/:slug/ping  →  {"ok": true}
        Called every ~30 seconds from the background worker thread.
        """
        url = f"{self.base_url}/device/{self.slug}/ping"
        try:
            resp = self.session.post(url, timeout=5)
            ok = resp.status_code == 200
            if ok:
                print(f"💓 [Heartbeat] ping OK")
            return ok
        except Exception as e:
            print(f"💔 [Heartbeat] ping failed: {e}")
            return False

    def poll_maintenance(self) -> Dict[str, Any]:
        """
        60s maintenance poll — checks device limits / config from backend.
        Also syncs latest settings (TTS config, volume, etc).
        """
        url = f"{self.base_url}/device/{self.slug}/settings"
        try:
            resp = self.session.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                docs = data.get("documents", [])
                if docs and isinstance(docs, list):
                    return docs[0]
        except Exception:
            pass
        return {}

    def fetch_pending_commands(self) -> list:
        """
        Fetch pending remote commands sent from the mobile/web dashboard.
        GET /device/:slug/commands/pending
        """
        url = f"{self.base_url}/device/{self.slug}/commands/pending"
        try:
            resp = self.session.get(url, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
                return data.get("commands", [])
            else:
                print(f"⚠️ [POLL] Backend returned HTTP {resp.status_code}", flush=True)
        except Exception as e:
            print(f"⚠️ [POLL] fetch_pending_commands failed: {e}", flush=True)
        return []


    def ack_command(self, cmd_id: str, success: bool, result: str):
        """Acknowledge command completion."""
        url = f"{self.base_url}/device/{self.slug}/commands/{cmd_id}/complete"
        try:
            self.session.post(url, json={"success": success, "result": result}, timeout=4)
        except Exception:
            pass

    def sync_alarms_to_cloud(self, alarms: list):
        url = f"{self.base_url}/device/{self.slug}/sync_alarms"
        try:
            self.session.post(url, json={"alarms": alarms}, timeout=5)
        except Exception:
            pass
