"""
Error Monitoring & Self-Healing System for RK AI Assistant V2.
Lightweight, thread-safe in-memory circular buffer with auto-persist.
Monitors error velocity and triggers self-healing or diagnostic alerts.
"""

import time
import json
import threading
import traceback
from pathlib import Path
from typing import Dict, List, Optional
from collections import deque, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime

from config import BASE_DIR

DATA_DIR = BASE_DIR / "data"
ERROR_LOG_PATH = DATA_DIR / "error_history.json"
MAX_ERROR_HISTORY = 300


@dataclass
class ErrorRecord:
    timestamp: float
    error_type: str
    severity: str  # 'critical', 'major', 'minor', 'info'
    message: str
    traceback: Optional[str] = None
    component: Optional[str] = None


class ErrorMonitor:
    """
    Lightweight error monitor tailored for Pi Zero W (512MB RAM).
    Tracks error rates and triggers alerts or self-healing callbacks.
    """

    THRESHOLDS = {
        "critical": (1, 60),    # 1 critical error in 60s
        "major": (3, 300),      # 3 major errors in 5 min
        "minor": (10, 600),     # 10 minor errors in 10 min
    }

    def __init__(self):
        self.error_history: deque = deque(maxlen=MAX_ERROR_HISTORY)
        self.error_counts: Dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
        self.last_alert_time = 0.0
        self.alert_cooldown = 180  # 3 minutes between voice/log alerts
        self._lock = threading.Lock()
        self._load_history()

    def _load_history(self):
        if ERROR_LOG_PATH.exists():
            try:
                data = json.loads(ERROR_LOG_PATH.read_text())
                for item in data.get("errors", [])[-50:]:
                    self.error_history.append(ErrorRecord(**item))
            except Exception as e:
                print(f"[error_monitor] History load note: {e}")

    def _save_history(self):
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "errors": [asdict(r) for r in list(self.error_history)[-100:]],
                "last_updated": time.time(),
            }
            ERROR_LOG_PATH.write_text(json.dumps(data, indent=2))
        except Exception as e:
            print(f"[error_monitor] History save note: {e}")

    def capture_exception(
        self,
        e: Exception,
        component: str = "general",
        severity: str = "major",
        extra_msg: str = "",
    ) -> bool:
        """Helper to record directly from an Exception block."""
        tb = traceback.format_exc()
        msg = f"{extra_msg}: {str(e)}" if extra_msg else str(e)
        return self.register_error(
            error_type=type(e).__name__,
            message=msg,
            severity=severity,
            traceback_str=tb,
            component=component,
        )

    def register_error(
        self,
        error_type: str,
        message: str,
        severity: str = "minor",
        traceback_str: Optional[str] = None,
        component: Optional[str] = None,
    ) -> bool:
        """
        Record error and check if threshold exceeded.
        Returns True if threshold triggered.
        """
        with self._lock:
            record = ErrorRecord(
                timestamp=time.time(),
                error_type=error_type,
                severity=severity,
                message=message,
                traceback=traceback_str,
                component=component or "system",
            )
            self.error_history.append(record)
            self.error_counts[error_type].append(record.timestamp)

            if len(self.error_history) % 5 == 0:
                self._save_history()

            should_alert = self._should_alert(severity, error_type)
            if should_alert:
                self.last_alert_time = time.time()
                print(f"🚨 [ErrorMonitor] THRESHOLD EXCEEDED for {severity} ({error_type}): {message}")

            return should_alert

    def _should_alert(self, severity: str, error_type: str) -> bool:
        now = time.time()
        if (now - self.last_alert_time) < self.alert_cooldown:
            return False

        if severity in self.THRESHOLDS:
            count_thresh, time_win = self.THRESHOLDS[severity]
            recent = [
                r for r in self.error_history
                if r.severity == severity and (now - r.timestamp) < time_win
            ]
            if len(recent) >= count_thresh:
                return True

        # Check repeating single error (e.g. 5 times in 2 mins)
        if error_type in self.error_counts:
            ts_list = self.error_counts[error_type]
            if len(ts_list) >= 5 and (now - list(ts_list)[-5]) < 120:
                return True

        return False

    def get_summary(self) -> Dict:
        """Returns statistics for system diagnostics."""
        with self._lock:
            recent = list(self.error_history)[-20:]
            counts = defaultdict(int)
            components = defaultdict(int)
            for r in recent:
                counts[r.severity] += 1
                components[r.component] += 1

            return {
                "total_recorded": len(self.error_history),
                "recent_count": len(recent),
                "by_severity": dict(counts),
                "by_component": dict(components),
                "latest_error": asdict(recent[-1]) if recent else None,
            }


# Singleton instance
_instance: Optional[ErrorMonitor] = None

def get_error_monitor() -> ErrorMonitor:
    global _instance
    if _instance is None:
        _instance = ErrorMonitor()
    return _instance
