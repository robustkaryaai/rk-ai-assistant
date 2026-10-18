import re
from typing import Optional, Dict, Any, Tuple

class FastCommandRouter:
    """
    Zero-latency, 0MB RAM rule-based instant matcher.
    Covers full feature catalog across Sections 1 to 5:
    - 1. Audio Controls (play, stop, pause, resume)
    - 2. Hardware Controls (volume, mute, reboot, poweroff, diagnostics)
    - 3. Alarms, Pomodoro, Period Bell, Voice Quiz
    - 4. Morning Routine ("good morning", "start my day"), Voice Notes
    - 5. Phone & IoT ("find my phone", "emergency/sos", "broadcast")
    """

    @staticmethod
    def route(text: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        if not text:
            return False, None
        
        cleaned = text.strip().lower()

        # ─── SECTION 1 & 2: PLAYBACK CONTROLS ───────────────
        if cleaned in ("stop", "pause", "shut up", "quiet", "silence", "halt", "cancel"):
            return True, {
                "reply": "Stopping.",
                "tool": "playback_control",
                "args": {"action": "stop"}
            }

        if cleaned in ("resume", "continue", "play"):
            return True, {
                "reply": "Resuming.",
                "tool": "playback_control",
                "args": {"action": "resume"}
            }

        # ─── SECTION 2: VOLUME CONTROLS (Instant ALSA amixer) ───
        if re.search(r"\b(volume up|louder|increase volume|turn it up)\b", cleaned):
            return True, {
                "reply": "Increasing volume.",
                "tool": "volume",
                "args": {"action": "up", "step": 10}
            }

        if re.search(r"\b(volume down|lower volume|decrease volume|quieter|turn it down)\b", cleaned):
            return True, {
                "reply": "Lowering volume.",
                "tool": "volume",
                "args": {"action": "down", "step": 10}
            }

        vol_match = re.search(r"\b(?:set )?volume (?:to )?(\d{1,3})\b", cleaned)
        if vol_match:
            level = max(0, min(100, int(vol_match.group(1))))
            return True, {
                "reply": f"Volume set to {level} percent.",
                "tool": "volume",
                "args": {"action": "set", "level": level}
            }

        if cleaned in ("mute", "go mute", "mute speaker"):
            return True, {
                "reply": "Muted speaker.",
                "tool": "volume",
                "args": {"action": "mute"}
            }

        if cleaned in ("unmute", "turn on sound", "unmute speaker"):
            return True, {
                "reply": "Unmuted speaker.",
                "tool": "volume",
                "args": {"action": "unmute"}
            }

        # ─── HARDWARE MIC MUTE / UNMUTE ──────────────────────
        if cleaned in ("mute mic", "mute microphone", "mic off", "turn off mic", "disable mic"):
            return True, {
                "reply": "Microphone muted at hardware level.",
                "tool": "hardware_mic",
                "args": {"action": "mute"}
            }

        if cleaned in ("unmute mic", "unmute microphone", "mic on", "turn on mic", "enable mic"):
            return True, {
                "reply": "Microphone unmuted.",
                "tool": "hardware_mic",
                "args": {"action": "unmute"}
            }

        # ─── TOGGLE NIGHT PROTOCOL ───────────────────────────
        if cleaned in ("disable night protocol", "turn off night protocol", "night mode off", "disable night mode"):
            return True, {
                "reply": "Night protocol disabled.",
                "tool": "night_mode_toggle",
                "args": {"enabled": False}
            }

        if cleaned in ("enable night protocol", "turn on night protocol", "night mode on", "enable night mode"):
            return True, {
                "reply": "Night protocol enabled.",
                "tool": "night_mode_toggle",
                "args": {"enabled": True}
            }

        # ─── SECTION 2.4: OFFLINE VOICE DIAGNOSTICS & BENCHMARK ──
        if re.search(r"\b(run diagnostics|check system|system status|health check)\b", cleaned):
            return True, {
                "reply": None,
                "tool": "diagnostics",
                "args": {}
            }

        if re.search(r"\b(run benchmark|developer mode|benchmark system|run developer mode)\b", cleaned):
            return True, {
                "reply": "Starting developer benchmark mode now. Check your terminal for live metrics.",
                "tool": "benchmark",
                "args": {}
            }

        # ─── SECTION 3: ALARMS & PERIOD BELLS ────────────────
        if re.search(r"\b(stop alarm|cancel alarm|turn off alarm|silence alarm)\b", cleaned):
            return True, {
                "reply": "Alarm stopped.",
                "tool": "alarm",
                "args": {"action": "stop"}
            }

        alarm_match = re.search(r"\b(?:set (?:an )?alarm for|wake me up at)\s+(\d{1,2}(?::\d{2})?(?:\s*[ap]m)?)\b", cleaned)
        if alarm_match:
            alarm_time = alarm_match.group(1).upper()
            return True, {
                "reply": f"Alarm set for {alarm_time}.",
                "tool": "alarm",
                "args": {"action": "set", "time": alarm_time, "label": "Alarm"}
            }

        if re.search(r"\b(ring (?:the )?period bell|ring bell|period bell)\b", cleaned):
            return True, {
                "reply": "Ringing period bell.",
                "tool": "period_bell",
                "args": {"label": "Period Bell"}
            }

        # ─── SECTION 3.3: POMODORO STUDY TIMER ───────────────
        pomo_match = re.search(r"\b(?:start|begin)\s+(\d{1,2})\s+minute\s+study(?:\s+session)?\b", cleaned)
        if pomo_match:
            mins = int(pomo_match.group(1))
            return True, {
                "reply": f"Starting {mins} minute Pomodoro study session.",
                "tool": "pomodoro",
                "args": {"action": "start", "minutes": mins}
            }

        if cleaned in ("start pomodoro", "start study session"):
            return True, {
                "reply": "Starting 25 minute Pomodoro study session.",
                "tool": "pomodoro",
                "args": {"action": "start", "minutes": 25}
            }

        if cleaned in ("stop pomodoro", "end study session", "cancel pomodoro"):
            return True, {
                "reply": "Ending Pomodoro session.",
                "tool": "pomodoro",
                "args": {"action": "stop"}
            }

        # ─── SECTION 3.5: INTERACTIVE VOICE QUIZ ─────────────
        quiz_match = re.search(r"\b(?:quiz me on|test me on|start quiz on)\s+(.+)$", cleaned)
        if quiz_match:
            topic = quiz_match.group(1).strip()
            return True, {
                "reply": f"Preparing your quiz on {topic}.",
                "tool": "quiz",
                "args": {"action": "start", "topic": topic}
            }

        if cleaned in ("cancel quiz", "stop quiz"):
            return True, {
                "reply": "Cancelling quiz.",
                "tool": "quiz",
                "args": {"action": "stop"}
            }

        # ─── SECTION 4.2: MORNING ROUTINE BRIEFING ───────────
        if cleaned in ("good morning", "start my day", "morning routine"):
            return True, {
                "reply": None,
                "tool": "morning_routine",
                "args": {}
            }

        # ─── SECTION: WEATHER COMMANDS ───────────────────────
        weather_match = re.search(r"\b(?:weather|temperature|forecast)(?:\s+(?:in|for|at)\s+([a-zA-Z\s]+))?\b", cleaned)
        if weather_match or "what's the weather" in cleaned or "how is the weather" in cleaned:
            target_city = weather_match.group(1).strip() if (weather_match and weather_match.group(1)) else "Delhi"
            return True, {
                "reply": None,
                "tool": "weather",
                "args": {"city": target_city}
            }

        # ─── SECTION: AUTOMATION ROUTINES ─────────────────────
        if re.search(r"\b(night protocol|good night|bedtime routine|goodnight protocol)\b", cleaned):
            return True, {
                "reply": None,
                "tool": "routine",
                "args": {"routine": "night_protocol"}
            }

        if re.search(r"\b(study mode|start study session|study protocol)\b", cleaned):
            return True, {
                "reply": None,
                "tool": "routine",
                "args": {"routine": "study_mode"}
            }

        if re.search(r"\b(work mode|focus mode|start work mode)\b", cleaned):
            return True, {
                "reply": None,
                "tool": "routine",
                "args": {"routine": "work_mode"}
            }

        if re.search(r"\b(relax mode|chill mode|calm down)\b", cleaned):
            return True, {
                "reply": None,
                "tool": "routine",
                "args": {"routine": "relax_mode"}
            }

        # ─── SECTION 4.3: VOICE BRAIN-DUMP / NOTES ───────────
        note_match = re.search(r"\b(?:note this down|take a note|save note)\s*:\s*(.+)$", cleaned)
        if note_match:
            note_content = note_match.group(1).strip()
            return True, {
                "reply": f"Saved note to your dashboard: {note_content}",
                "tool": "note",
                "args": {"content": note_content}
            }

        # ─── SECTION 5.1: FIND MY PHONE ──────────────────────
        if re.search(r"\b(where is my phone|find my phone|ring my phone)\b", cleaned):
            return True, {
                "reply": None,
                "tool": "find_phone",
                "args": {}
            }

        # ─── SECTION 5.4: EMERGENCY SOS SIREN ────────────────
        if re.search(r"\b(emergency|sos|help me|panic alarm)\b", cleaned):
            return True, {
                "reply": None,
                "tool": "emergency_sos",
                "args": {}
            }

        # ─── SECTION 1.3: DIRECT MUSIC STREAMING ─────────────
        play_match = re.search(r"\bplay\s+(.+?)(?:\s+on\s+(youtube|spotify))?$", cleaned)
        if play_match:
            query = play_match.group(1).strip()
            service = play_match.group(2) or "youtube"
            if query not in ("music", "song", "something", ""):
                return True, {
                    "reply": f"Alright, playing {query} on {service}.",
                    "tool": "music",
                    "args": {"query": query, "service": service}
                }

        # ─── HARDWARE POWER ACTIONS ──────────────────────────
        if cleaned in ("restart", "reboot", "reboot pi", "restart pi", "reboot system", "rk reboot"):
            return True, {
                "reply": "Rebooting system now.",
                "tool": "system",
                "args": {"action": "reboot"}
            }

        if cleaned in ("shutdown", "power off", "turn off pi", "rk shutdown"):
            return True, {
                "reply": "Shutting down system.",
                "tool": "system",
                "args": {"action": "shutdown"}
            }

        if cleaned in ("status", "how are you"):
            return True, {
                "reply": "RK AI is active, connected to speaker, and running smoothly.",
                "tool": "status",
                "args": {}
            }

        # Fall through to backend
        return False, None
