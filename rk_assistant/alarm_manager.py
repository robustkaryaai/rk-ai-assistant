"""Alarm manager for RK AI Assistant."""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path
from typing import Optional, Dict, List

from .audio_utils import speak
from .config import DATA_DIR

ALARMS_FILE = DATA_DIR / "alarms.json"


def load_alarms() -> List[Dict]:
    """Load alarms from JSON file."""
    if not ALARMS_FILE.exists():
        return []
    try:
        with open(ALARMS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def save_alarms(alarms: List[Dict]) -> None:
    """Save alarms to JSON file."""
    try:
        with open(ALARMS_FILE, "w") as f:
            json.dump(alarms, f, indent=2)
    except Exception as e:
        print(f"[alarm] Failed to save alarms: {e}")


def parse_time(time_str: str) -> Optional[str]:
    """Parse time string to HH:MM format.
    
    Supports formats like:
    - "8 AM", "8:30 AM", "8:30 PM"
    - "20:00", "08:00"
    - "eight o'clock", "half past eight"
    """
    time_str = time_str.lower().strip()
    
    # Try to extract HH:MM format
    import re
    
    # Format: "8 AM", "8:30 PM"
    match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', time_str)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        period = match.group(3)
        
        if period == 'pm' and hour != 12:
            hour += 12
        elif period == 'am' and hour == 12:
            hour = 0
            
        return f"{hour:02d}:{minute:02d}"
    
    # Format: "20:00", "08:00"
    match = re.search(r'(\d{1,2}):(\d{2})', time_str)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if 0 <= hour < 24 and 0 <= minute < 60:
            return f"{hour:02d}:{minute:02d}"
    
    # Relative time: "in 5 minutes", "10 mins", "1 hour"
    match = re.search(r'(\d+)\s*(?:m|min|minute|minutes|h|hr|hour|hours)', time_str)
    if match:
        val = int(match.group(1))
        # Check unit
        now = dt.datetime.now()
        delta = dt.timedelta(minutes=0)
        
        if 'h' in time_str or 'hour' in time_str:
            delta = dt.timedelta(hours=val)
        else:
            delta = dt.timedelta(minutes=val)
            
        future = now + delta
        return future.strftime("%H:%M")

    return None


def set_alarm(time_str: str, label: str = "Alarm") -> bool:
    """Set an alarm for the given time."""
    parsed_time = parse_time(time_str)
    if not parsed_time:
        return False
    
    alarms = load_alarms()
    alarm = {
        "time": parsed_time,
        "label": label,
        "enabled": True,
        "created_at": dt.datetime.now().isoformat()
    }
    alarms.append(alarm)
    save_alarms(alarms)
    
    # Start alarm checker thread if not running
    start_alarm_checker()
    
    return True


def cancel_all_alarms() -> int:
    """Cancel all alarms. Returns count of canceled alarms."""
    alarms = load_alarms()
    count = len(alarms)
    save_alarms([])
    return count


def list_alarms() -> List[Dict]:
    """List all active alarms."""
    return [a for a in load_alarms() if a.get("enabled", True)]


_alarm_checker_running = False


def start_alarm_checker() -> None:
    """Start background thread to check alarms."""
    global _alarm_checker_running
    
    if _alarm_checker_running:
        return
    
    _alarm_checker_running = True
    
    def check_alarms():
        while _alarm_checker_running:
            try:
                alarms = load_alarms()
                now = dt.datetime.now()
                current_time = now.strftime("%H:%M")
                
                triggered = []
                remaining = []
                
                for alarm in alarms:
                    if not alarm.get("enabled", True):
                        continue
                    
                    alarm_time = alarm.get("time", "")
                    if alarm_time == current_time:
                        # Trigger alarm
                        label = alarm.get("label", "Alarm")
                        speak(f"Alarm! {label}")
                        speak(f"It's {alarm_time}")
                        triggered.append(alarm)
                    else:
                        remaining.append(alarm)
                
                # Remove triggered alarms
                if triggered:
                    save_alarms(remaining)
                
            except Exception as e:
                print(f"[alarm] Checker error: {e}")
            
            time.sleep(30)  # Check every 30 seconds
    
    thread = threading.Thread(target=check_alarms, daemon=True)
    thread.start()


def prompt_for_alarm_time() -> Optional[str]:
    """Prompt user for alarm time via voice. Returns time string or None."""
    from .audio_utils import quick_stt, load_pocketsphinx_decoder
    
    speak("What time should I set the alarm?")
    
    # Listen for time
    decoder_available = load_pocketsphinx_decoder()
    time_text = quick_stt(decoder_available, seconds=5)
    
    if not time_text:
        speak("I didn't catch that.")
        return None
    
    return time_text
