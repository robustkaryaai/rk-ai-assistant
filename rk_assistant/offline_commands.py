"""Offline command router."""

from __future__ import annotations

import datetime as dt
import time
import random
from typing import Optional

from .audio_utils import play_audio_url, set_volume, speak, stop_process
from .config import OFFLINE_COMMANDS

OFFLINE_AI_RESPONSES = [f"Got it, noted {i}." for i in range(1, 101)]

# Response templates for different command categories
GREETING_RESPONSES = {
    "hello": ["Hello! How can I help you?", "Hi there!", "Hello! Nice to hear from you!"],
    "hi": ["Hi! What can I do for you?", "Hey there!", "Hi! I'm listening."],
    "hey": ["Hey! How can I assist?", "Hey there!", "Hey! What's up?"],
    "good morning": ["Good morning! Hope you have a great day!", "Good morning! How can I help?"],
    "good afternoon": ["Good afternoon! What can I do for you?", "Good afternoon!"],
    "good evening": ["Good evening! How may I assist?", "Good evening!"],
    "good night": ["Good night! Sleep well!", "Good night! See you tomorrow!"],
}

CONVERSATIONAL_RESPONSES = {
    "how are you": ["I'm doing great! Thanks for asking.", "I'm fine, thank you! How about you?"],
    "what's up": ["Not much, just waiting to help you!", "All good here! What about you?"],
    "thank you": ["You're welcome!", "Happy to help!", "Anytime!"],
    "thanks": ["No problem!", "You're welcome!", "My pleasure!"],
    "okay": ["Okay!", "Got it!", "Understood!"],
    "yes": ["Yes!", "Affirmative!", "Okay!"],
    "no": ["No problem!", "Alright!", "Okay!"],
    "goodbye": ["Goodbye! Take care!", "See you later!", "Bye! Have a great day!"],
    "bye": ["Bye!", "See you!", "Goodbye!"],
}


import re

def match_offline_command(text: str) -> Optional[str]:
    """Return matched command keyword if present as a WHOLE WORD."""
    text = (text or "").lower()
    for cmd in OFFLINE_COMMANDS:
        # Use regex to match whole words only (e.g. "hi" won't match "something")
        if re.search(rf"\b{re.escape(cmd)}\b", text):
            return cmd
    return None



def process_offline_command(cmd: str, music_proc=None) -> str:
    """Execute offline actions and return response text."""
    cmd = (cmd or "").lower()
    
    # Greeting commands
    if cmd in GREETING_RESPONSES:
        return random.choice(GREETING_RESPONSES[cmd])
    
    # Conversational commands
    if cmd in CONVERSATIONAL_RESPONSES:
        return random.choice(CONVERSATIONAL_RESPONSES[cmd])
    
    # Music controls
    if cmd in {"play music", "resume music"}:
        return "No cached music URL. Please ask online."
    elif cmd in {"pause music", "stop music", "stop", "pause", "quiet", "shut up", "silence", "exit"}:
        from . import music_manager
        music_manager.stop_music()
        return "Stopped."
    elif cmd == "volume up" or cmd == "increase volume":
        set_volume(+10)
        return "Volume up."
    elif cmd == "volume down" or cmd == "decrease volume":
        set_volume(-10)
        return "Volume down."
    elif cmd in {"mute"}:
        set_volume(-50)
        return "Muted."
    elif cmd in {"unmute"}:
        set_volume(+20)
        return "Unmuted."
    
    # Time and date
    elif any(x in cmd for x in ["time", "what time"]):
        now = dt.datetime.now()
        return now.strftime("It is %I:%M %p.")
    elif any(x in cmd for x in ["date", "what's the date", "today's date"]):
        now = dt.datetime.now()
        return now.strftime("Today is %A, %B %d, %Y.")
    
    # Announcements
    elif cmd in {"announcement", "announce", "make announcement"}:
        return "Ready for your announcement."

    # Weather (Works if internet is available, even if backend is down)
    elif cmd in {"weather", "what's the weather", "weather today"}:
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
    
    # Alarms (basic offline support)
    elif cmd in {"set alarm"}:
        from .alarm_manager import prompt_for_alarm_time, set_alarm
        time_str = prompt_for_alarm_time()
        if time_str and set_alarm(time_str):
            return f"Alarm set for {time_str}."
        else:
            return "Could not set alarm. Please try again."
    elif cmd in {"cancel alarm", "delete alarm", "stop alarm"}:
        from .alarm_manager import cancel_all_alarms
        count = cancel_all_alarms()
        if count > 0:
            return f"Canceled {count} alarm{'s' if count != 1 else ''}."
        else:
            return "No alarms to cancel."
    
    # System info
    elif cmd in {"battery", "battery level", "battery status"}:
        return "Battery information not available in offline mode."
    elif cmd in {"status", "system status"}:
        return "System is running in offline mode."
    
    # Assistant info
    elif cmd in {"who are you", "what's your name", "introduce yourself"}:
        return "I am RK AI, your personal assistant created by RK Innovators."
    elif cmd in {"help", "help me", "what can you do"}:
        return "I can help with music playback, alarms, time, date, and basic commands. For more features, connect to the internet."
    elif cmd in {"commands", "list commands", "available commands"}:
        return "I support greetings, music controls, time and date queries, alarms, and system commands. Ask me anything!"
    
    # Nice responses
    elif cmd in {"nice", "great", "awesome", "cool", "wonderful", "excellent", "perfect"}:
        responses = ["Thank you!", "Glad you liked it!", "Great to hear!", "Awesome!"]
        return random.choice(responses)
    
    return "I am currently offline and cannot process that command."


