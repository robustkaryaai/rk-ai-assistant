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

    def __init__(self, base_url: str, slug: str, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.slug = slug
        self.timeout = timeout
        self.session = requests.Session()

    def send_text(self, text: str) -> Dict[str, Any]:
        """
        Send user voice transcript or text query to RK_AI_HOME.
        The backend runs Gemini, processes cloud tasks, and returns:
          {
            "reply": "Spoken text for the speaker",
            "local_action": {"tool": "music"|"alarm"|"bell"|None, "args": {...}}
          }
        """
        url = f"{self.slug and f'{self.base_url}/text/{self.slug}' or f'{self.base_url}/text'}"
        payload = {"text": text}
        try:
            resp = self.session.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return self._parse_backend_response(data)
        except Exception as e:
            return {
                "reply": "I'm having trouble connecting to my cloud backend.",
                "local_action": None,
                "error": str(e)
            }

    def _parse_backend_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Strips cloud generation tasks (already executed on backend)
        and extracts only local hardware actions for the Pi.
        """
        reply = data.get("reply", "")
        intents: List[Dict[str, Any]] = data.get("intents", [])
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

        # Cloud tools (image, video, docx, ppt, exam_paper, grading_sheet, class_planner, note)
        # are executed entirely in the backend. Pi only needs to speak the confirmation `reply`!
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
