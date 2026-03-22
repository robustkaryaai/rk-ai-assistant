"""
Command Poller - Polls backend for pending commands and executes them
Mobile App → Backend (Appwrite queue) → Pi polls and executes
"""
import os
import time
import requests
from threading import Thread, Lock
from typing import Optional

from .config import BACKEND_BASE_URL
from .audio_utils import set_volume
from . import audio_utils_simple
from .error_monitor import register_error
from . import schedule_manager
from . import alarm_manager

# Global flag for mute state
_muted = False

# Circuit breaker state
_consecutive_failures = 0
_last_success_time = 0
_backoff_until = 0
MAX_FAILURES_BEFORE_BACKOFF = 5
BACKOFF_DURATION = 15  # seconds — keep short so device recovers fast after Wi-Fi reboot


def _mark_command_complete(cmd_id, slug: str, result: str, success: bool, cmd_type: str) -> None:
    try:
        requests.post(
            f"{BACKEND_BASE_URL}/device/{slug}/commands/{cmd_id}/complete",
            json={"result": result, "success": success},
            timeout=10,
        )
        print(f"[commands] ✓ {cmd_type} completed: {result}")
    except Exception as e:
        print(f"[commands] Failed to mark command complete: {e}")


def set_mute(muted: bool) -> str:
    """Set mute state"""
    global _muted
    _muted = muted
    if muted:
        set_volume(0)
        return "Device muted"
    else:
        set_volume(50)
        return "Device unmuted"

def get_mute_state() -> bool:
    """Get current mute state"""
    return _muted

# Callback function to handle voice commands (set by main.py)
_voice_command_callback = None

def register_voice_callback(callback):
    """Register callback function to execute voice commands"""
    global _voice_command_callback
    _voice_command_callback = callback

def execute_voice_command(text: str) -> str:
    """Execute a voice command (send to backend for processing)"""
    try:
        if _voice_command_callback:
            # Execute via callback (non-blocking thread ideally, but fine for now)
            # We return immediately to acknowledge receipt
            # The callback handles speaking/processing
            Thread(target=_voice_command_callback, args=(text,), daemon=True).start()
            return f"Command '{text}' executing..."
        else:
            # Fallback
            audio_utils_simple.speak(f"Executing command: {text}")
            return f"Command '{text}' queued (no handler)"
    except Exception as e:
        return f"Error: {str(e)}"

def execute_command(cmd: dict, slug: str) -> None:
    """Execute a single command from the queue"""
    cmd_id = cmd.get('$id')
    # 🚀 Check for both snake_case and camelCase from Appwrite schema
    cmd_type = cmd.get('command_type') or cmd.get('commandType')
    payload = cmd.get('payload', {})
    
    print(f"[commands] Executing {cmd_type}: {payload}")
    
    try:
        # Execute based on command type
        if cmd_type == 'voice':
            text = payload.get('text', '')
            result = execute_voice_command(text)
            success = True
            
        elif cmd_type == 'mute' or cmd_type == 'set_mute':
            mute_val = payload.get('mute', True) if cmd_type == 'set_mute' else True
            result = set_mute(mute_val)
            success = True
            
        elif cmd_type == 'unmute':
            result = set_mute(False)
            success = True
            
        elif cmd_type == 'volume':
            volume = payload.get('volume', 50)
            set_volume(volume)
            result = f"Volume set to {volume}%"
            success = True
            
        elif cmd_type == 'broadcast':
            text = payload.get('text', '')
            if text:
                audio_utils_simple.speak(text)
            result = f"Broadcasted: {text}"
            success = True
            
        elif cmd_type == 'set_schedule':
            s_id = payload.get('id', str(int(time.time())))
            date = payload.get('date')
            time_str = payload.get('time')
            task = payload.get('task')
            is_recurring = payload.get('isRecurring', False)
            days = payload.get('days', [])
            schedule_manager.add_schedule(s_id, date, time_str, task, is_recurring, days)
            result = f"Schedule set: {task} at {date or days} {time_str}"
            success = True
            try:
                requests.post(f"{BACKEND_BASE_URL}/device/{slug}/sync_schedules", json={"schedules": schedule_manager.list_schedules()}, timeout=5)
            except: pass
            
        elif cmd_type == 'delete_schedule':
            s_id = payload.get('schedule_id')
            schedule_manager.delete_schedule(s_id)
            result = f"Schedule deleted: {s_id}"
            success = True
            try:
                requests.post(f"{BACKEND_BASE_URL}/device/{slug}/sync_schedules", json={"schedules": schedule_manager.list_schedules()}, timeout=5)
            except: pass

        elif cmd_type == 'set_alarm':
            time_str = payload.get('time')
            label = payload.get('label', 'Alarm')
            sound = payload.get('sound', 'default')
            wake_up_message = payload.get('wakeUpMessage')
            days = payload.get('days', [])
            
            if alarm_manager.set_alarm(time_str, label, sound, wake_up_message, days):
                result = f"Alarm set for {time_str}"
                success = True
                try:
                    requests.post(f"{BACKEND_BASE_URL}/device/{slug}/sync_alarms", json={"alarms": alarm_manager.list_alarms()}, timeout=5)
                except: pass
            else:
                result = "Failed to set alarm"
                success = False

        elif cmd_type == 'delete_alarm':
            a_id = payload.get('alarm_id')
            try:
                if hasattr(alarm_manager, 'delete_alarm'):
                    alarm_manager.delete_alarm(a_id)
                else: 
                    alarm_manager.cancel_all_alarms()
                requests.post(f"{BACKEND_BASE_URL}/device/{slug}/sync_alarms", json={"alarms": alarm_manager.list_alarms()}, timeout=5)
            except: pass
            result = "Alarm deleted"
            success = True
            
        elif cmd_type == 'reboot' or cmd_type == 'text_command':
            text = payload.get('text', '')
            if text:
                # Treat as if it was spoken to the device
                execute_voice_command(text)
            result = f"Processing command: {text}"
            success = True
            
        elif cmd_type == 'shutdown':
            audio_utils_simple.speak("Shutting down RexyCore Assistant")
            result = "Shutdown initiated"
            success = True
            # Note: Actual shutdown would be handled externally
            
        elif cmd_type == 'set_wifi':
            ssid = payload.get('ssid')
            password = payload.get('password', '')
            if ssid:
                audio_utils_simple.speak(f"Received new Wi-Fi credentials for {ssid}. I will reboot and connect now.")
                result = f"Applying Wi-Fi credentials for {ssid}"
                success = True
                
                # We must mark it complete BEFORE rebooting, so do it manually here
                try:
                    requests.post(
                        f"{BACKEND_BASE_URL}/device/{slug}/commands/{cmd_id}/complete",
                        json={"result": result, "success": success},
                        timeout=5
                    )
                except: pass
                
                # Execute the Wi-Fi switch and reboot
                from .ble_provisioning import apply_wifi
                import threading
                threading.Thread(target=apply_wifi, args=(ssid, password), daemon=True).start()
                return # Exit this execution
            else:
                result = "Missing SSID in set_wifi payload"
                success = False

        elif cmd_type == 'scan_network':
            cid, dev_slug = cmd_id, slug

            def _scan_worker():
                try:
                    audio_utils_simple.speak("Scanning local network for smart appliances...")
                    from .smart_home import discover_and_sync_devices
                    scan_res = discover_and_sync_devices(dev_slug)
                    count = scan_res.get("count", 0)
                    if scan_res.get("success"):
                        audio_utils_simple.speak(f"Scan complete. Found {count} native devices.")
                        _mark_command_complete(
                            cid, dev_slug,
                            f"Network scan completed. Found {count} devices.",
                            True,
                            "scan_network",
                        )
                    else:
                        audio_utils_simple.speak("Network scan encountered an error.")
                        _mark_command_complete(
                            cid, dev_slug,
                            f"Scan failed: {scan_res.get('error')}",
                            False,
                            "scan_network",
                        )
                except Exception as ex:
                    audio_utils_simple.speak("Network scan encountered an error.")
                    _mark_command_complete(
                        cid, dev_slug, f"Scan crashed: {ex}", False, "scan_network",
                    )

            Thread(target=_scan_worker, daemon=True).start()
            return

        elif cmd_type == 'control_device':
            from .smart_home import control_device_by_id
            device_id = payload.get('id') or payload.get('device_id')
            action = (payload.get('action') or 'toggle').lower()
            if not device_id:
                result = "control_device: missing id in payload"
                success = False
            else:
                result = control_device_by_id(str(device_id), action)
                fail_markers = (
                    "couldn't find",
                    "no device with id",
                    "didn't respond",
                    "don't have",
                    "unknown action",
                    "add a",
                    "toggle needs",
                    "not installed",
                )
                success = not any(m in result.lower() for m in fail_markers)

        elif cmd_type == 'ecosystem_routine':
            routine = payload.get('routine', 'lumina_coding')
            from .desktop_link import trigger_desktop_action
            from . import smart_home
            if routine == 'lumina_coding':
                amb = smart_home.run_coding_ambience()
                audio_utils_simple.speak(amb)
                ok = trigger_desktop_action(
                    'lumina_coding_session',
                    {
                        'folder': payload.get('folder'),
                        'ide': payload.get('ide'),
                    },
                    slug=slug,
                )
                result = f"Lumina flow: lights done, desktop relay {'ok' if ok else 'failed'}."
                success = bool(ok)
            else:
                result = f"Unknown ecosystem routine: {routine}"
                success = False

        else:
            result = f"Unknown command type: {cmd_type}"
            success = False
        
        # Mark command as complete
        try:
            requests.post(
                f"{BACKEND_BASE_URL}/device/{slug}/commands/{cmd_id}/complete",
                json={"result": result, "success": success},
                timeout=10
            )
            print(f"[commands] ✓ {cmd_type} completed: {result}")
        except Exception as e:
            print(f"[commands] Failed to mark command complete: {e}")
            
    except Exception as e:
        error_msg = f"Execution error: {str(e)}"
        print(f"[commands] ✗ {cmd_type} failed: {error_msg}")
        
        # Try to mark as failed
        try:
            requests.post(
                f"{BACKEND_BASE_URL}/device/{slug}/commands/{cmd_id}/complete",
                json={"result": error_msg, "success": False},
                timeout=10
            )
        except:
            pass  # Silently fail if we can't report the failure

def poll_commands(slug: str) -> None:
    """Poll backend for pending commands with health check and exponential backoff"""
    global _consecutive_failures, _last_success_time, _backoff_until
    
    print(f"[commands] Command poller started for device {slug}")
    
    # First, do a health check
    if not _check_backend_health():
        print("[commands] Backend health check failed, using degraded mode")
    
    while True:
        try:
            # Check if in backoff period
            if time.time() < _backoff_until:
                remaining = int(_backoff_until - time.time())
                if remaining % 30 == 0:  # Log every 30s during backoff
                    print(f"[commands] In backoff mode, resuming in {remaining}s")
                time.sleep(5)
                continue
            
            # Get pending commands from backend
            response = requests.get(
                f"{BACKEND_BASE_URL}/device/{slug}/commands/pending",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                commands = data.get('commands', [])
                
                if commands:
                    print(f"[commands] Fetched {len(commands)} pending command(s)")
                
                for cmd in commands:
                    execute_command(cmd, slug)
                
                # Reset failure counter on success
                _consecutive_failures = 0
                _last_success_time = time.time()
            
            elif response.status_code == 500:
                _consecutive_failures += 1
                error_msg = f"Backend returned 500 error (attempt {_consecutive_failures})"
                print(f"[commands] {error_msg}")
                
                # Register error for monitoring
                register_error(
                    error_type="backend_500_error",
                    message=error_msg,
                    severity="major" if _consecutive_failures >= 3 else "minor",
                    file_path=__file__
                )
                
                # Trigger backoff if too many failures
                if _consecutive_failures >= MAX_FAILURES_BEFORE_BACKOFF:
                    _backoff_until = time.time() + BACKOFF_DURATION
                    print(f"[commands] Too many failures, backing off for {BACKOFF_DURATION}s")
            
            elif response.status_code == 404:
                print(f"[commands] Endpoint not found (404) - backend may not have device registered")
                time.sleep(30)  # Wait longer for 404s
            
            else:
                print(f"[commands] Poll failed with status {response.status_code}")
                _consecutive_failures += 1
                
        except requests.exceptions.Timeout:
            # Silent timeout log if frequent
            if _consecutive_failures % 5 == 0:
                print("[commands] Poll timeout (retrying in 5s...)")
            _consecutive_failures += 1
            time.sleep(5) # Force sleep
        except requests.exceptions.ConnectionError:
            print("[commands] No backend connection (continuing...)")
            _consecutive_failures += 1
        except Exception as e:
            print(f"[commands] Poll error: {e}")
            _consecutive_failures += 1
            register_error(
                error_type="command_poller_error",
                message=str(e),
                severity="minor",
                file_path=__file__
            )
        
        # Dynamic poll interval based on failure rate
        if _consecutive_failures > 0:
            sleep_time = min(5 * _consecutive_failures, 30)  # Max 30s
        else:
            sleep_time = 5
        
        time.sleep(sleep_time)


def _check_backend_health() -> bool:
    """Check if backend is reachable and healthy"""
    try:
        # Try to reach backend root
        response = requests.get(f"{BACKEND_BASE_URL}/health", timeout=5)
        return response.status_code == 200
    except:
        try:
            # Fallback: try base URL
            response = requests.get(BACKEND_BASE_URL, timeout=5)
            return response.status_code < 500
        except:
            return False

_poller_thread = None
_poller_lock = Lock()

def start_command_poller(slug: str) -> None:
    """Start background thread to poll for commands"""
    global _poller_thread
    with _poller_lock:
        if _poller_thread and _poller_thread.is_alive():
            print("[commands] Command poller already running, skipping start.")
            return
            
        _poller_thread = Thread(target=poll_commands, args=(slug,), daemon=True)
        _poller_thread.start()
        print("[commands] Background command poller started")
