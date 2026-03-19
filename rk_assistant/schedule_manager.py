import json
import os
import time
import threading
from datetime import datetime
from .audio_utils_simple import speak

SCHEDULE_FILE = "/tmp/rk_schedules.json"

def load_schedules():
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return []

def save_schedules(schedules):
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(schedules, f)

def add_schedule(id, date, time_str, task):
    schedules = load_schedules()
    schedules.append({
        "id": id,
        "date": date,
        "time": time_str,
        "task": task,
        "active": True
    })
    save_schedules(schedules)
    print(f"[schedules] Added: {task} at {date} {time_str}")

def delete_schedule(schedule_id):
    schedules = load_schedules()
    schedules = [s for s in schedules if s["id"] != schedule_id]
    save_schedules(schedules)
    print(f"[schedules] Deleted: {schedule_id}")

def schedule_loop(voice_callback):
    """Background loop to check and execute schedules."""
    print("[schedules] Monitoring scheduled tasks...")
    while True:
        try:
            now = datetime.now()
            current_date = now.strftime("%Y-%m-%d")
            current_time = now.strftime("%H:%M")
            
            schedules = load_schedules()
            updated = False
            
            for s in schedules:
                if s["active"] and s["date"] == current_date and s["time"] == current_time:
                    print(f"[schedules] Triggering task: {s['task']}")
                    # Mark as inactive first to prevent double-triggering
                    s["active"] = False
                    updated = True
                    
                    # Execute task
                    if voice_callback:
                        threading.Thread(target=voice_callback, args=(s["task"],), daemon=True).start()
                    else:
                        speak(f"Executing scheduled task: {s['task']}")
            
            if updated:
                save_schedules(schedules)
                
            time.sleep(30) # Check every 30s
        except Exception as e:
            print(f"[schedules] Error in loop: {e}")
            time.sleep(60)

def start_schedule_monitor(voice_callback):
    t = threading.Thread(target=schedule_loop, args=(voice_callback,), daemon=True)
    t.start()
    return t
