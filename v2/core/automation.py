"""
Automation & Multi-Step Routine Engine for RK AI Assistant V2.
Executes routines (night protocol, study mode, morning routine, work mode).
Safe, non-blocking execution across volume, speech, alarms, and music.
"""

import time
import threading
from typing import Dict, List, Any, Optional


ROUTINES: Dict[str, List[Dict[str, Any]]] = {
    "night_protocol": [
        {"action": "speak", "data": "Initiating Night Protocol."},
        {"action": "volume", "data": 20},
        {"action": "alarm", "data": "07:00 AM"},
        {"action": "speak", "data": "Goodnight, Boss. Sweet dreams."},
    ],
    "work_mode": [
        {"action": "speak", "data": "Focus mode activated. Let's get things done."},
        {"action": "volume", "data": 45},
        {"action": "pomodoro", "data": 25},
    ],
    "study_mode": [
        {"action": "speak", "data": "Study session initiated. Silencing distractions."},
        {"action": "volume", "data": 35},
        {"action": "pomodoro", "data": 30},
    ],
    "relax_mode": [
        {"action": "speak", "data": "Relax mode engaged. Setting volume to comfortable level."},
        {"action": "volume", "data": 40},
        {"action": "music", "data": "lofi chill beats"},
    ],
}


class AutomationEngine:
    def __init__(self, assistant):
        self.assistant = assistant

    def execute_routine(self, routine_name: str) -> bool:
        """Runs the sequence of actions in a background thread."""
        key = routine_name.strip().lower().replace(" ", "_")
        steps = ROUTINES.get(key)
        if not steps:
            print(f"[automation] Routine '{routine_name}' not found.")
            return False

        def _worker():
            print(f"🎬 [Automation] Running routine: {key}")
            for step in steps:
                act = step.get("action")
                data = step.get("data")
                try:
                    if act == "speak":
                        self.assistant.speak(str(data))
                    elif act == "volume":
                        self.assistant.player.set_system_volume("set", int(data))
                    elif act == "alarm":
                        self.assistant.alarm_mgr.set_alarm(time_str=str(data), label="Routine Alarm")
                    elif act == "pomodoro":
                        self.assistant.pomodoro.start(study_minutes=int(data))
                    elif act == "music":
                        self.assistant.handle_command(f"play {data}")
                    time.sleep(0.4)
                except Exception as e:
                    print(f"[automation] Step {act} failed: {e}")

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return True
