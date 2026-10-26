import json
import time
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

class AlarmScheduleManager:
    """
    Two-Way Alarm & Schedule Manager (Step 3: Section 3 in FEATURES.md).
    - Operates locally on Pi (never misses an alarm even if offline).
    - Syncs with Appwrite / RK_AI_HOME cloud (/device/:slug/sync_alarms).
    - Handles alarms, recurring weekday schedules, and period bells.
    """

    def __init__(self, data_dir: Path, client=None, player=None, tts=None):
        self.data_dir = data_dir
        self.alarms_file = data_dir / "alarms.json"
        self.schedules_file = data_dir / "schedules.json"
        self.client = client
        self.player = player
        self.tts = tts
        self.active_ringing_alarm = None

        self._ensure_files()

    def _ensure_files(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.alarms_file.exists():
            self.alarms_file.write_text("[]")
        if not self.schedules_file.exists():
            self.schedules_file.write_text("[]")

    def load_alarms(self) -> List[Dict[str, Any]]:
        try:
            return json.loads(self.alarms_file.read_text())
        except Exception:
            return []

    def save_alarms(self, alarms: List[Dict[str, Any]], sync_to_cloud: bool = True):
        self.alarms_file.write_text(json.dumps(alarms, indent=2))
        if sync_to_cloud and self.client:
            self.client.sync_alarms_to_cloud(alarms)

    def set_alarm(self, time_str: str, label: str = "Alarm", days: Optional[List[str]] = None, wake_up_message: str = "") -> Dict[str, Any]:
        """
        Sets a new local alarm.
        Example time_str: "07:00", "7:00 AM", "19:30"
        """
        alarms = self.load_alarms()
        alarm_id = str(int(time.time() * 1000))
        new_alarm = {
            "id": alarm_id,
            "time": time_str,
            "label": label,
            "days": days or [],
            "wakeUpMessage": wake_up_message or f"Radhe Radhe! It is {time_str}. Time for {label}.",
            "active": True
        }
        alarms.append(new_alarm)
        self.save_alarms(alarms, sync_to_cloud=True)
        return new_alarm

    def delete_alarm(self, alarm_id: str) -> bool:
        """Deletes an alarm by ID and syncs to cloud."""
        alarms = self.load_alarms()
        filtered = [a for a in alarms if str(a.get("id")) != str(alarm_id)]
        if len(filtered) != len(alarms):
            self.save_alarms(filtered, sync_to_cloud=True)
            print(f"🗑️ [ALARM] Deleted alarm: {alarm_id}", flush=True)
            return True
        return False

    def delete_schedule(self, schedule_id: str) -> bool:
        """Deletes a schedule by ID."""
        try:
            schedules = json.loads(self.schedules_file.read_text()) if self.schedules_file.exists() else []
            filtered = [s for s in schedules if str(s.get("id")) != str(schedule_id)]
            self.schedules_file.write_text(json.dumps(filtered, indent=2))
            print(f"🗑️ [SCHEDULE] Deleted schedule: {schedule_id}", flush=True)
            return True
        except Exception as e:
            print(f"❌ [SCHEDULE] Delete error: {e}", flush=True)
            return False

    def stop_alarm(self) -> bool:
        if self.player:
            self.player.stop()
        self.active_ringing_alarm = None
        return True

    def ring_period_bell(self, label: str = "Period Bell"):
        """Audio chime + spoken announcement for classroom/study period transitions."""
        print(f"🔔 [PERIOD BELL] Ringing: {label}")
        bell_sound = Path(__file__).resolve().parent.parent / "data" / "sounds" / "period_bell.wav"
        if self.player:
            self.player.set_system_volume("set", 90)
            if bell_sound.exists():
                self.player.play_url_or_file(str(bell_sound), sync=True)
            else:
                self.player.play_chime("ready", sync=True)
        if self.tts:
            self.tts.speak(f"Period bell: {label}")

    def check_alarms_tick(self):
        """Called every second by the main cooperative loop."""
        now = datetime.datetime.now()
        current_time_24 = now.strftime("%H:%M")
        current_time_12 = now.strftime("%I:%M %p").lstrip("0")
        current_day = now.strftime("%A")

        alarms = self.load_alarms()
        changed = False

        for alarm in alarms:
            if not alarm.get("active"):
                continue

            alarm_time = alarm.get("time", "").strip()
            alarm_days = alarm.get("days", [])

            # Check matching time (both 24h & 12h formats supported)
            time_matches = (alarm_time == current_time_24) or (alarm_time.upper() == current_time_12.upper())
            day_matches = True if not alarm_days else (current_day in alarm_days)

            # Avoid re-triggering multiple times in the same minute
            if time_matches and day_matches and alarm.get("last_triggered") != current_time_24:
                alarm["last_triggered"] = current_time_24
                changed = True
                self._trigger_alarm(alarm)

                # Non-recurring alarm disables after ring
                if not alarm_days:
                    alarm["active"] = False

        if changed:
            self.save_alarms(alarms, sync_to_cloud=False)

    def _trigger_alarm(self, alarm: Dict[str, Any]):
        print(f"⏰ [ALARM TRIGGERED] {alarm.get('label')} at {alarm.get('time')}")
        self.active_ringing_alarm = alarm

        # 1. Play real alarm tone from assets/alarms
        sound_name = alarm.get("sound", "default")
        alarms_dir = Path(__file__).resolve().parent.parent / "assets" / "alarms"
        chosen_file = None
        if alarms_dir.exists():
            candidates = list(alarms_dir.glob("*.mp3"))
            if candidates:
                # Find matching or pick first default alarm tone
                for f in candidates:
                    if sound_name.lower() in f.name.lower():
                        chosen_file = str(f)
                        break
                if not chosen_file:
                    chosen_file = str(candidates[0])

        if chosen_file and self.player:
            print(f"🔔 [ALARM] Playing alarm tone: {chosen_file}")
            self.player.play_url_or_file(chosen_file)
            time.sleep(4)  # Ring tone for 4s before speaking

        # 2. Speak personalized wake-up message
        msg = alarm.get("wakeUpMessage", f"Wake up! Alarm for {alarm.get('time')}")
        if self.tts:
            self.tts.speak(msg)
