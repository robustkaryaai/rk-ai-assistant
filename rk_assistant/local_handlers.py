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
    
    # For now, return a simple response
    # In the future, this could search YouTube/Spotify locally
    return {
        "intent": "music",
        "reply": f"Playing {prompt}",
        "song_url": None  # Pi will search and play
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
    
    # This could trigger special emergency protocols
    return {
        "intent": "emergency_alarm",
        "reply": f"⚠️ EMERGENCY: {prompt}"
    }


def handle_intent(intent: str, parameters: Dict[str, Any], original_text: str = "") -> Dict[str, Any]:
    """
    Main router for local intent handling.
    
    Args:
        intent: Intent name
        parameters: Intent parameters
        original_text: Original user text (for chat context)
        
    Returns:
        Response dict with 'intent' and 'reply' fields
    """
    print(f"[local] Handling intent locally: {intent}", flush=True)
    
    if intent == "music":
        return handle_music(parameters)
    
    elif intent == "alarm":
        return handle_alarm(parameters)
    
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
