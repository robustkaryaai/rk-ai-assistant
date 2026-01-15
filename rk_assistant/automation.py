"""
RK AI Automation Engine (God Mode).
Executes multi-step routines across devices.
"""
import time
from .audio_utils import speak, set_volume
from .networking import post_text_to_backend
# from .local_handlers import ...

ROUTINES = {
    "night_protocol": [
        {"action": "speak", "data": "Initiating Night Protocol."},
        {"action": "volume", "data": 20},
        {"action": "backend", "data": {"target": "astra", "command": "shutdown"}}, # Future Astra
        {"action": "alarm", "data": "07:00 AM"},
        {"action": "speak", "data": "Goodnight, Boss."}
    ],
    "work_mode": [
        {"action": "speak", "data": "Focus mode activated."},
        {"action": "volume", "data": 50},
        {"action": "music", "data": "LoFi Beats"},
    ]
}

def execute_routine(routine_name: str, slug: str) -> bool:
    """Execute a predefined routine."""
    steps = ROUTINES.get(routine_name.lower().replace(" ", "_"))
    
    if not steps:
        print(f"[automation] Routine '{routine_name}' not found.")
        return False
        
    print(f"[automation] Executing routine: {routine_name}")
    
    for step in steps:
        action = step.get("action")
        data = step.get("data")
        
        try:
            if action == "speak":
                speak(str(data))
                
            elif action == "volume":
                set_volume(int(data))
                
            elif action == "backend":
                # Send command to other devices via backend
                # We format this as a text command "tell astra to shutdown" or direct JSON if backend supports it
                if isinstance(data, dict):
                    # Placeholder for direct JSON
                    pass 
                
            elif action == "alarm":
                from .alarm_manager import set_alarm
                set_alarm(str(data))
                
            elif action == "music":
                from .music_manager import play_music
                play_music(str(data))
                
            time.sleep(0.5) # Pace out actions
            
        except Exception as e:
            print(f"[automation] Step failed: {step} - {e}")
            
    return True
