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
        The backend runs Gemini, processes cloud tasks, and returns:
          {
            "reply": "Spoken text for the speaker",
            "local_action": {"tool": "music"|"alarm"|"bell"|None, "args": {...}}
          }
        """
        url = f"{self.base_url}/text/{self.slug}"
        payload = {"text": text}
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return self._parse_backend_response(data)
        except Exception as e:
            print(f"[backend] Connection error: {e}")
            return {
                "reply": None,
                "local_action": None,
                "error": str(e)
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

    def poll_maintenance(self) -> Dict[str, Any]:
        """
        60s heartbeat poller for device limits and status.
        """
        url = f"{self.base_url}/device/{self.slug}/maintenance"
        try:
            resp = self.session.get(url, timeout=5)
            return resp.json()
        except Exception:
            return {}

    def sync_alarms_to_cloud(self, alarms: list):
        url = f"{self.base_url}/device/{self.slug}/sync_alarms"
        try:
            self.session.post(url, json={"alarms": alarms}, timeout=5)
        except Exception:
            pass
