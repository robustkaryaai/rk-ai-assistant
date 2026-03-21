"""Alarm manager for RK AI Assistant."""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
import os
import subprocess
from pathlib import Path
from typing import Optional, Dict, List

from .audio_utils_simple import speak
from .config import DATA_DIR

ALARMS_FILE = DATA_DIR / "alarms.json"
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "alarms")


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


def set_alarm(time_str: str, label: str = "Alarm", sound: str = "default", wake_up_message: Optional[str] = None, days: Optional[List[str]] = None) -> bool:
    """Set an alarm for the given time."""
    parsed_time = parse_time(time_str)
    if not parsed_time:
        return False
    
    alarms = load_alarms()
    alarm = {
        "time": parsed_time,
        "label": label,
        "sound": sound,
        "wake_up_message": wake_up_message,
        "days": days or [],
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


def stop_all_alarms() -> None:
    """Stop any currently ringing alarm currently playing."""
    global _alarm_active, _alarm_sound_procs
    print("[alarm] Stopping all alarms...")
    _alarm_active = False
    # Kill all running sound processes
    for proc in list(_alarm_sound_procs):
        try:
            proc.kill()
        except Exception:
            pass
    _alarm_sound_procs = []
    
    # Aggressively kill system-level players
    import subprocess
    subprocess.run(["killall", "-9", "paplay"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    subprocess.run(["killall", "-9", "mpg123"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)


def list_alarms() -> List[Dict]:
    """List all active alarms."""
    return [a for a in load_alarms() if a.get("enabled", True)]


# Track running alarm sound processes so we can stop them
_alarm_sound_procs: List[subprocess.Popen] = []
_alarm_active = False


def play_alarm_sound(sound_file: Optional[str]):
    """Plays the selected alarm sound using paplay. Interruptible via stop_all_alarms()."""
    global _alarm_sound_procs, _alarm_active
    if not sound_file or sound_file == "default":
        sound_file = "freesound_community-alarm-clock-short-6402.mp3"
    
    full_path = os.path.join(ASSETS_DIR, sound_file)
    if os.path.exists(full_path):
        print(f"[alarm] Playing sound: {full_path}")
        _alarm_active = True
        
        proc = subprocess.Popen(["paplay", full_path],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _alarm_sound_procs.append(proc)
        proc.wait()
        _alarm_sound_procs = [p for p in _alarm_sound_procs if p.poll() is None]
        
        _alarm_active = False
    else:
        print(f"[alarm] Sound file not found: {full_path}")


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
                current_day = now.strftime("%a") # e.g. "Mon"
                
                updated_alarms = []
                any_triggered = False
                
                for alarm in alarms:
                    if not alarm.get("enabled", True):
                        updated_alarms.append(alarm)
                        continue
                    
                    alarm_time = alarm.get("time", "")
                    alarm_days = alarm.get("days", [])
                    
                    # Check if day matches (or if no days specified, treat as one-time)
                    day_matches = not alarm_days or current_day in alarm_days
                    
                    if alarm_time == current_time and day_matches:
                        # Avoid double-triggering in same minute (both for recurring AND one-time)
                        if alarm.get("triggered_today"):
                            updated_alarms.append(alarm)
                            continue
                        
                        # Trigger alarm
                        print(f"[alarm] 🚨 TRIGGERING: {alarm.get('label', 'Alarm')} at {current_time}")
                        
                        # Sequential Trigger to ensure both are heard and PulseAudio handles mixing correctly
                        def run_alarm_logic(sound_file, wakeup_msg):
                            # 1. Force PulseAudio sink refresh before playing
                            try:
                                subprocess.run(['pacmd', 'list-sinks'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            except:
                                pass
                                
                            # 2. Play Sound
                            play_alarm_sound(sound_file)
                            # 3. Short Pause to let the sound start/settle
                            time.sleep(1.5)
                            # 4. Speak Message
                            speak(wakeup_msg)

                        msg = alarm.get("wake_up_message") or f"Radhe Radhe! It's {alarm_time}. Time for {alarm.get('label', 'Alarm')}."
                        # Use a dedicated thread for the alarm logic so it doesn't block the checker
                        t = threading.Thread(target=run_alarm_logic, args=(alarm.get("sound"), msg), daemon=True)
                        t.start()
                        
                        any_triggered = True
                        
                        # Mark as triggered to prevent re-firing within the same minute
                        alarm["triggered_today"] = True
                        if alarm_days:
                            # Recurring: keep in list
                            updated_alarms.append(alarm)
                        else:
                            # One-time: keep with triggered_today flag until minute changes, then it's removed
                            updated_alarms.append(alarm)
                    else:
                        # Reset "triggered_today" if the minute has passed
                        if alarm_time != current_time:
                            alarm.pop("triggered_today", None)
                        updated_alarms.append(alarm)
                
                if any_triggered or len(updated_alarms) != len(alarms):
                    save_alarms(updated_alarms)
                
            except Exception as e:
                print(f"[alarm] Checker error: {e}")
            
            time.sleep(30)  # Check every 30 seconds
    
    thread = threading.Thread(target=check_alarms, daemon=True)
    thread.start()


def prompt_for_alarm_time() -> Optional[str]:
    """Prompt user for alarm time via voice. Returns time string or None."""
    from .audio_utils import record_audio, quick_stt
    
    speak("What time should I set the alarm?")
    
    # Listen for time
    audio_path = record_audio()
    if not audio_path:
        speak("I didn't hear anything.")
        return None
        
    time_text = quick_stt(str(audio_path))
    
    if not time_text:
        speak("I didn't catch that.")
        return None
    
    return time_text
