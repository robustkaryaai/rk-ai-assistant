"""
Command Poller - Polls backend for pending commands and executes them
Mobile App → Backend (Appwrite queue) → Pi polls and executes
"""
import os
import time
import requests
from threading import Thread
from typing import Optional

from .config import BACKEND_BASE_URL
from .audio_utils import set_volume
from . import audio_utils_simple

# Global flag for mute state
_muted = False

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

def execute_voice_command(text: str) -> str:
    """Execute a voice command (send to backend for processing)"""
    try:
        # For now, just speak the command acknowledgment
        # In future, this will integrate with the main command processing
        audio_utils_simple.speak(f"Executing command: {text}")
        return f"Command '{text}' queued for execution"
    except Exception as e:
        return f"Error: {str(e)}"

def execute_command(cmd: dict, slug: str) -> None:
    """Execute a single command from the queue"""
    cmd_id = cmd.get('$id')
    cmd_type = cmd.get('command_type')
    payload = cmd.get('payload', {})
    
    print(f"[commands] Executing {cmd_type}: {payload}")
    
    try:
        # Execute based on command type
        if cmd_type == 'voice':
            text = payload.get('text', '')
            result = execute_voice_command(text)
            success = True
            
        elif cmd_type == 'mute':
            result = set_mute(True)
            success = True
            
        elif cmd_type == 'unmute':
            result = set_mute(False)
            success = True
            
        elif cmd_type == 'volume':
            volume = payload.get('volume', 50)
            set_volume(volume)
            result = f"Volume set to {volume}%"
            success = True
            
        elif cmd_type == 'shutdown':
            audio_utils_simple.speak("Shutting down RK AI Assistant")
            result = "Shutdown initiated"
            success = True
            # Note: Actual shutdown would be handled externally
            
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
    """Poll backend for pending commands every 5 seconds"""
    print(f"[commands] Command poller started for device {slug}")
    
    while True:
        try:
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
            
            elif response.status_code != 200:
                print(f"[commands] Poll failed with status {response.status_code}")
                
        except requests.exceptions.Timeout:
            print("[commands] Poll timeout (continuing...)")
        except requests.exceptions.ConnectionError:
            print("[commands] No backend connection (continuing...)")
        except Exception as e:
            print(f"[commands] Poll error: {e}")
        
        # Poll every 5 seconds
        time.sleep(5)

def start_command_poller(slug: str) -> None:
    """Start background thread to poll for commands"""
    thread = Thread(target=poll_commands, args=(slug,), daemon=True)
    thread.start()
    print("[commands] Background command poller started")
