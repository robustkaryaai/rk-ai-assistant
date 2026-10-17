import time
from typing import Optional

class PomodoroTimer:
    """
    Pomodoro Study Timer (Feature 3.3).
    - Study Block (e.g. 25 mins) -> Period Bell + Break (e.g. 5 mins) -> Re-ring to resume.
    - Zero thread bloat; tick evaluated in main cooperative loop.
    """

    def __init__(self, alarm_manager, tts):
        self.alarm_mgr = alarm_manager
        self.tts = tts
        self.is_active = False
        self.current_phase = None # "study" or "break"
        self.phase_end_time = 0.0
        self.study_duration = 25 * 60
        self.break_duration = 5 * 60

    def start(self, study_minutes: int = 25, break_minutes: int = 5):
        self.study_duration = study_minutes * 60
        self.break_duration = break_minutes * 60
        self.current_phase = "study"
        self.phase_end_time = time.time() + self.study_duration
        self.is_active = True

        msg = f"Pomodoro study session started for {study_minutes} minutes. Focus time!"
        print(f"🍅 [POMODORO] {msg}")
        self.tts.speak(msg)

    def stop(self):
        if self.is_active:
            self.is_active = False
            self.current_phase = None
            self.tts.speak("Pomodoro session ended.")

    def tick(self):
        if not self.is_active:
            return

        now = time.time()
        if now >= self.phase_end_time:
            if self.current_phase == "study":
                # Study phase finished -> Period bell -> Start break
                self.alarm_mgr.ring_period_bell("Study session completed. Time for a 5 minute break!")
                self.current_phase = "break"
                self.phase_end_time = now + self.break_duration
            elif self.current_phase == "break":
                # Break phase finished -> Period bell -> Resume study
                self.alarm_mgr.ring_period_bell("Break is over! Time to start the next study session.")
                self.current_phase = "study"
                self.phase_end_time = now + self.study_duration
