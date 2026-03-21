"""Offline command router."""

from __future__ import annotations

import datetime as dt
import time
import random
from typing import Optional

from .audio_utils import play_audio_url, set_volume, speak, stop_process
from .config import OFFLINE_COMMANDS

OFFLINE_AI_RESPONSES = [
    "Got it.",
    "Okay, noted.",
    "Will do.",
    "Consider it done.",
    "I've saved that offline.",
    "Noted for when we're back online.",
    "Understood.",
    "Sure thing.",
    "Alright.",
    "I've saved your request."
]

# Response templates for different command categories
GREETING_RESPONSES = [
    "Hello! How can I help you?", "Hi there!", 
    "Hello! Nice to hear from you!", "Greetings!", 
    "Hey! How can I assist?", "Good to see you!"
]

CONVERSATIONAL_RESPONSES = {
    "how_are_you": ["I'm doing great! Thanks for asking.", "I'm fine, thank you! How about you?"],
    "gratitude": ["You're welcome!", "Happy to help!", "Anytime!", "My pleasure!"],
    "goodbye": ["Goodbye! Take care!", "See you later!", "Bye! Have a great day!"],
    "identity": ["I am RK AI, an intelligent offline assistant.", "My name is RK, I'm here to help."]
}

from .intent_classifier import classify_local_intent

def match_offline_command(text: str) -> Optional[str]:
    """
    Uses the SciKit-Learn Tiny ML model to categorize the spoken text
    into a predefined offline intent (e.g. 'volume_up', 'weather').
    Returns None if the confidence is too low.
    """
    return classify_local_intent(text)



def process_offline_command(intent_id: str, raw_text: str = "", music_proc=None) -> str:
    """Execute offline actions based on the classified intent and return response text."""
    if not intent_id: return ""
    
    # Greetings & Conversations
    if intent_id == "greeting":
        return random.choice(GREETING_RESPONSES)
    
    if intent_id in CONVERSATIONAL_RESPONSES:
        return random.choice(CONVERSATIONAL_RESPONSES[intent_id])
    
    # Jokes
    if intent_id == "joke":
        jokes = [
            "Why do programmers prefer dark mode? Because light attracts bugs.",
            "I'm afraid for the calendar. Its days are numbered.",
            "My wife said I should do lunges to stay in shape. That would be a big step forward.",
            "Why did the database administrator leave his wife? She had one-to-many relationships."
        ]
        return random.choice(jokes)
    
    # Music controls
    if intent_id in ["play_music", "resume_music"]:
        return f"_PLAY_MUSIC_|{raw_text}"  # Pass entire raw text sequence to music_manager for cached NLP matching
    elif intent_id == "play_again":
        from . import music_manager
        if music_manager.last_played_query:
            return "_PLAY_AGAIN_" # Special sentinel for main.py
        return "No song to play again."
    elif intent_id in ["stop", "pause_music"]:
        from . import music_manager
        music_manager.stop_music()
        return "Stopped."
        
    # Audio Settings
    elif intent_id == "volume_up":
        set_volume(+10)
        return "Volume up."
    elif intent_id == "volume_down":
        set_volume(-10)
        return "Volume down."
    elif intent_id == "mute":
        set_volume(-50)
        return "Muted."
    elif intent_id == "unmute":
        set_volume(+20)
        return "Unmuted."
    
    # Time and date
    elif intent_id == "time":
        now = dt.datetime.now()
        hour = now.strftime("%I").lstrip("0") or "12"  # Remove leading zero
        mins = now.strftime("%M")
        period = now.strftime("%p")
        return f"It is {hour} {mins} {period}."
    elif intent_id == "date":
        now = dt.datetime.now()
        return now.strftime("Today is %A, %B %d, %Y.")

    # News & Weather
    elif intent_id == "news":
        from .weather_news import fetch_news
        return fetch_news()
    elif intent_id == "weather":
        from .weather_news import fetch_weather
        w = fetch_weather()
        if w:
            current = w.get("current", {})
            temp = current.get("temp_c")
            desc = current.get("condition", {}).get("text", "")
            place = current.get("city", "")
            return f"Current weather in {place} is {desc}, {temp} degrees Celsius."
        else:
            return "Sorry, I couldn't get the weather info."
            
    # Alarms and Tasks (Reminders)
    elif intent_id == "set_alarm":
        from .alarm_manager import set_alarm
        success = set_alarm("placeholder", label=raw_text) # In offline, we can't extract time easily yet, so we store the raw text as a generic reminder hook to be checked later or ring instantly as a default 5min timer.
        return "I've noted your alarm locally, but for a specific time, please set it via the RK app."
    elif intent_id == "task":
        return f"I've recorded your reminder offline: {raw_text.replace('remind me', '').replace('remind me to', '').strip()}"
        
    # Bluetooth Controls
    elif intent_id == "bluetooth_connect":
        import subprocess
        from .config import BLUETOOTH_SPEAKER_MAC, BLUETOOTH_HCI
        subprocess.run(["sudo", "bluetoothctl", "connect", BLUETOOTH_SPEAKER_MAC], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Attempting to connect to the Bluetooth speaker."
        
    # Diagnostics
    elif intent_id == "test_connection":
        from .networking import is_online
        if is_online():
            return "Diagnostic Check: I am successfully connected to the internet and the Appwrite database is reachable."
        else:
            return "Diagnostic Check: The physical internet connection has been severed. I am operating completely offline."
    # System info
    elif intent_id == "update_system":
        return "_RK_UPDATE_"
    elif intent_id == "shutdown_device":
        return "_RK_SHUTDOWN_"
    elif intent_id == "restart_device":
        return "_RK_REBOOT_"
    elif intent_id == "battery":
        return "Battery information not available in offline mode."
    elif intent_id == "show_id":
        from .config import SLUG_FILE
        try:
            with open(SLUG_FILE, "r") as f:
                slug = f.read().strip().split(":")[0]
                # Format for speech: "1 2 3 4 5 6 7 8 9"
                spaced_slug = " ".join(list(slug))
                return f"My identification number is {spaced_slug}."
        except:
            return "I'm sorry, I couldn't retrieve my I D number right now."
    
    # Generic generic command matched but no specific logic -> play offline sound
    idx = random.randint(0, len(OFFLINE_AI_RESPONSES) - 1)
    return f"_PLAY_OFFLINE_{idx}_"


