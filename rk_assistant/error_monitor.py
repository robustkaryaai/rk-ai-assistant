"""
Error Monitoring System for RK AI Assistant.
Tracks errors, detects patterns, and triggers self-diagnosis when needed.
"""

import time
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from datetime import datetime
import threading

from .config import BASE_DIR, DATA_DIR

# Error storage
ERROR_LOG_PATH = DATA_DIR / "error_monitor.json"
MAX_ERROR_HISTORY = 1000

@dataclass
class ErrorRecord:
    """Single error record"""
    timestamp: float
    error_type: str
    severity: str  # 'critical', 'major', 'minor', 'info'
    message: str
    traceback: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    context: Optional[Dict] = None


class ErrorMonitor:
    """Monitors system errors and triggers self-diagnosis when thresholds are exceeded."""
    
    # Severity thresholds (count within time_window triggers diagnosis)
    THRESHOLDS = {
        'critical': (1, 60),      # 1 critical error in 60s → diagnose
        'major': (3, 300),        # 3 major errors in 5min → diagnose
        'minor': (10, 600),       # 10 minor errors in 10min → diagnose
    }
    
    def __init__(self):
        self.error_history: deque = deque(maxlen=MAX_ERROR_HISTORY)
        self.error_counts: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.diagnosis_in_progress = False
        self.last_diagnosis_time = 0
        self.diagnosis_cooldown = 300  # 5 minutes between diagnoses
        self._lock = threading.Lock()
        self._load_history()
    
    def _load_history(self):
        """Load error history from disk"""
        if ERROR_LOG_PATH.exists():
            try:
                with open(ERROR_LOG_PATH, 'r') as f:
                    data = json.load(f)
                    for record_dict in data.get('errors', [])[-100:]:  # Load last 100
                        record = ErrorRecord(**record_dict)
                        self.error_history.append(record)
            except Exception as e:
                print(f"[error_monitor] Failed to load history: {e}")
    
    def _save_history(self):
        """Save error history to disk"""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                'errors': [asdict(record) for record in list(self.error_history)],
                'last_updated': time.time()
            }
            with open(ERROR_LOG_PATH, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[error_monitor] Failed to save history: {e}")
    
    def register_error(
        self,
        error_type: str,
        message: str,
        severity: str = 'minor',
        traceback: Optional[str] = None,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None,
        context: Optional[Dict] = None
    ) -> bool:
        """
        Register an error and check if diagnosis should be triggered.
        
        Returns:
            True if diagnosis should be triggered, False otherwise
        """
        with self._lock:
            record = ErrorRecord(
                timestamp=time.time(),
                error_type=error_type,
                severity=severity,
                message=message,
                traceback=traceback,
                file_path=file_path,
                line_number=line_number,
                context=context or {}
            )
            
            self.error_history.append(record)
            self.error_counts[error_type].append(record.timestamp)
            
            # Save to disk periodically
            if len(self.error_history) % 10 == 0:
                self._save_history()
            
            # Check if diagnosis should be triggered
            should_diagnose = self.should_trigger_diagnosis(severity, error_type)
            
            if should_diagnose:
                print(f"[error_monitor] 🚨 Diagnosis triggered for {severity} error: {error_type}")
            
            return should_diagnose
    
    def should_trigger_diagnosis(self, severity: str = None, error_type: str = None) -> bool:
        """
        Check if error thresholds have been exceeded.
        
        Args:
            severity: Check specific severity level thresholds
            error_type: Check specific error type frequency
        """
        # Don't trigger if diagnosis already in progress
        if self.diagnosis_in_progress:
            return False
        
        # Don't trigger if within cooldown period
        if time.time() - self.last_diagnosis_time < self.diagnosis_cooldown:
            return False
        
        current_time = time.time()
        
        # Check severity-based thresholds
        if severity and severity in self.THRESHOLDS:
            count_threshold, time_window = self.THRESHOLDS[severity]
            
            # Count errors of this severity in the time window
            recent_errors = [
                r for r in self.error_history
                if r.severity == severity and (current_time - r.timestamp) < time_window
            ]
            
            if len(recent_errors) >= count_threshold:
                return True
        
        # Check error type frequency (if same error occurs repeatedly)
        if error_type and error_type in self.error_counts:
            timestamps = self.error_counts[error_type]
            if len(timestamps) >= 5:  # At least 5 occurrences
                # Check if last 5 occurred within 2 minutes
                recent_5 = list(timestamps)[-5:]
                if current_time - recent_5[0] < 120:  # 2 minutes
                    return True
        
        return False
    
    def get_error_context(self, severity: str = None, limit: int = 20) -> Dict:
        """
        Get recent error context for diagnosis report.
        
        Args:
            severity: Filter by severity level
            limit: Maximum number of errors to include
        
        Returns:
            Dictionary with error statistics and recent errors
        """
        with self._lock:
            recent_errors = list(self.error_history)[-limit:]
            
            if severity:
                recent_errors = [e for e in recent_errors if e.severity == severity]
            
            # Calculate statistics
            error_types = defaultdict(int)
            severity_counts = defaultdict(int)
            files_affected = set()
            
            for error in recent_errors:
                error_types[error.error_type] += 1
                severity_counts[error.severity] += 1
                if error.file_path:
                    files_affected.add(error.file_path)
            
            return {
                'total_errors': len(recent_errors),
                'error_types': dict(error_types),
                'severity_distribution': dict(severity_counts),
                'files_affected': list(files_affected),
                'recent_errors': [
                    {
                        'timestamp': datetime.fromtimestamp(e.timestamp).isoformat(),
                        'type': e.error_type,
                        'severity': e.severity,
                        'message': e.message,
                        'file': e.file_path,
                        'line': e.line_number,
                        'traceback': e.traceback
                    }
                    for e in recent_errors[-10:]  # Last 10 for detailed report
                ]
            }
    
    def set_diagnosis_status(self, in_progress: bool):
        """Update diagnosis status"""
        with self._lock:
            self.diagnosis_in_progress = in_progress
            if not in_progress:
                self.last_diagnosis_time = time.time()
    
    def clear_old_errors(self, older_than_seconds: int = 3600):
        """Clear errors older than specified time (default: 1 hour)"""
        with self._lock:
            current_time = time.time()
            cutoff_time = current_time - older_than_seconds
            
            # Keep only recent errors
            self.error_history = deque(
                (e for e in self.error_history if e.timestamp > cutoff_time),
                maxlen=MAX_ERROR_HISTORY
            )
            
            # Clear old timestamps from error_counts
            for error_type in list(self.error_counts.keys()):
                self.error_counts[error_type] = deque(
                    (t for t in self.error_counts[error_type] if t > cutoff_time),
                    maxlen=100
                )
            
            self._save_history()


# Global singleton instance
_monitor_instance = None

def get_monitor() -> ErrorMonitor:
    """Get or create global error monitor instance"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = ErrorMonitor()
    return _monitor_instance


def register_error(error_type: str, message: str, **kwargs) -> bool:
    """
    Convenience function to register error on global monitor.
    Returns True if diagnosis should be triggered.
    """
    return get_monitor().register_error(error_type, message, **kwargs)
