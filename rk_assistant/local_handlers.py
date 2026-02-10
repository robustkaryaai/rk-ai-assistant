"""
Local intent handlers for Pi.
Handles intents that can be processed on the Pi without backend.
"""

from __future__ import annotations

from typing import Dict, Any
from . import gemini_client
from .config import GEMINI_API_KEY, GEMINI_MODEL


def handle_music(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle music playback intent locally.
    Returns response with song info for Pi to play.
    """
    prompt = parameters.get("prompt", "music")
    
    # Delegate to Music Manager (Handles Cache + Streaming)
    # The actual playback process will be started by main.py using the returned info
    # But wait, local_handlers just returns data struct. 
    # We need to change how local_handlers works or how main.py treats it.
    
    # OPTION A: Return a special flag to main.py to call music_manager
    # OPTION B: Call music_manager here and return the process? 
    # Current architecture: main.py expects a dict with 'reply' and 'intent'.
    # If intent is music, main.py looks for 'song_url'.
    
    # Let's change this:
    # Return intent="music_local", and the query.
    
    return {
        "intent": "music_local",
        "reply": f"Searching for {prompt}",
        "query": prompt
    }


def handle_alarm(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle alarm setting intent locally.
    Uses Pi's alarm_manager module.
    """
    from .alarm_manager import set_alarm
    
    alarm_time = parameters.get("time")
    prompt = parameters.get("prompt", "alarm")
    
    if alarm_time:
        # Try to set the alarm
        success = set_alarm(alarm_time)
        if success:
            return {
                "intent": "alarm",
                "reply": f"Alarm set for {alarm_time}",
                "time": alarm_time
            }
        else:
            return {
                "intent": "alarm",
                "reply": "Could not set alarm. Invalid time format.",
                "time": None
            }
    else:
        # No time provided
        return {
            "intent": "alarm",
            "reply": "What time should I set the alarm?",
            "time": None
        }


def handle_announcement(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle announcement intent locally.
    Returns announcement text to be spoken twice.
    """
    announcement_text = parameters.get("prompt", "Announcement")
    
    return {
        "intent": "announcement",
        "reply": announcement_text
    }


def handle_chat(text: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle chat/general intent using Gemini conversational mode.
    """
    # Use Gemini for conversational response
    reply = gemini_client.get_conversational_response(
        text,
        api_key=GEMINI_API_KEY,
        model_name=GEMINI_MODEL
    )
    
    return {
        "intent": "chat",
        "reply": reply
    }


def handle_stop_alarm(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle stop/cancel alarm intent locally.
    """
    from .alarm_manager import stop_all_alarms
    
    try:
        stop_all_alarms()
        return {
            "intent": "stop_alarm",
            "reply": "Alarm stopped"
        }
    except Exception as e:
        print(f"[local] Error stopping alarm: {e}")
        return {
            "intent": "stop_alarm",
            "reply": "Could not stop alarm"
        }


def handle_emergency_alarm(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle emergency/fire alarm intent locally.
    """
    prompt = parameters.get("prompt", "Emergency alert")
    
    return {
        "reply": f"⚠️ EMERGENCY: {prompt}"
    }


def handle_memory(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle 'remember' intent.
    Stores the text in long-term memory.
    """
    from .memory_engine import store_memory
    
    text = parameters.get("prompt", "")
    # Clean up text: remove "remember that" etc.
    # Simple cleanup for now
    clean_text = text.replace("remember that", "").replace("remember", "").strip()
    
    if clean_text:
        store_memory(clean_text)
        return {
            "intent": "remember",
            "reply": f"Okay, I've remembered that {clean_text}."
        }
    else:
        return {
            "intent": "remember",
            "reply": "What would you like me to remember?"
        }


def handle_task(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle task/reminder intent locally.
    Simple acknowledgment for now - can be extended to actually set reminders.
    """
    prompt = parameters.get("prompt", "reminder")
    time = parameters.get("time", "")
    
    if time:
        reply = f"Got it, I'll remind you about {prompt} in {time}"
    else:
        reply = f"Okay, noted: {prompt}"
    
    return {
        "intent": "task",
        "reply": reply
    }


def handle_intent(intent: str, parameters: Dict[str, Any], original_text: str = "") -> Dict[str, Any]:
    """
    Main router for local intent handling.
    """
    print(f"[local] Handling intent locally: {intent}", flush=True)
    
    if intent == "music":
        return handle_music(parameters)
    
    elif intent == "alarm":
        return handle_alarm(parameters)
    
    elif intent == "task":
        return handle_task(parameters)
    
    elif intent == "remember":
        return handle_memory(parameters)
    
    elif intent == "mute":
        return {"intent": "mute", "reply": "Muting microphone. Say 'RK Unmute' meant to be heard but I can't hear you now. You must physically restart or use the app to unmute."}
        # Note: True voice unmute is hard if we stop listening. Usually "Mute" means "Stop responding" or "Stop sending to cloud".
    
    elif intent == "announcement":
        return handle_announcement(parameters)
    
    elif intent in ["chat", "general"]:
        return handle_chat(original_text, parameters)
    
    elif intent == "stop_alarm":
        return handle_stop_alarm(parameters)
    
    elif intent in ["emergency_alarm", "fire_alarm"]:
        return handle_emergency_alarm(parameters)
    
    else:
        # Unknown local intent, return generic response
        print(f"[local] Unknown local intent: {intent}", flush=True)
        return {
            "intent": intent,
            "reply": f"Processing {intent}"
        }
