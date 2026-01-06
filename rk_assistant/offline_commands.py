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


def match_offline_command(text: str) -> Optional[str]:
    """Return matched command keyword if present."""
    text = (text or "").lower()
    for cmd in OFFLINE_COMMANDS:
        if cmd in text:
            return cmd
    return None


def handle_offline_command(cmd: str, music_proc) -> None:
    """Execute lightweight actions."""
    # Greeting commands
    if cmd in GREETING_RESPONSES:
        response = random.choice(GREETING_RESPONSES[cmd])
        speak(response)
        return
    
    # Conversational commands
    if cmd in CONVERSATIONAL_RESPONSES:
        response = random.choice(CONVERSATIONAL_RESPONSES[cmd])
        speak(response)
        return
    
    # Music controls
    if cmd in {"play music", "resume music"}:
        speak("No cached music URL. Please ask online.")
    elif cmd in {"pause music", "stop music"}:
        stop_process(music_proc)
        speak("Paused.")
    elif cmd == "volume up" or cmd == "increase volume":
        set_volume(+5)
        speak("Volume up.")
    elif cmd == "volume down" or cmd == "decrease volume":
        set_volume(-5)
        speak("Volume down.")
    elif cmd in {"mute"}:
        set_volume(-50)
        speak("Muted.")
    elif cmd in {"unmute"}:
        set_volume(+20)
        speak("Unmuted.")
    
    # Time and date
    elif cmd in {"time", "what time is it", "current time"}:
        now = dt.datetime.now()
        speak(now.strftime("It is %I:%M %p."))
    elif cmd in {"date", "what's the date", "today's date"}:
        now = dt.datetime.now()
        speak(now.strftime("Today is %A, %B %d, %Y."))
    
    # Announcements
    elif cmd in {"announcement", "announce", "make announcement"}:
        speak("Ready for your announcement.")
    
    # Alarms (basic offline support)
    elif cmd in {"set alarm"}:
        from .alarm_manager import prompt_for_alarm_time, set_alarm
        time_str = prompt_for_alarm_time()
        if time_str and set_alarm(time_str):
            speak(f"Alarm set for {time_str}.")
        else:
            speak("Could not set alarm. Please try again.")
    elif cmd in {"cancel alarm", "delete alarm", "stop alarm"}:
        from .alarm_manager import cancel_all_alarms
        count = cancel_all_alarms()
        if count > 0:
            speak(f"Canceled {count} alarm{'s' if count != 1 else ''}.")
        else:
            speak("No alarms to cancel.")
    
    # System info
    elif cmd in {"battery", "battery level", "battery status"}:
        speak("Battery information not available in offline mode.")
    elif cmd in {"status", "system status"}:
        speak("System is running in offline mode.")
    
    # Assistant info
    elif cmd in {"who are you", "what's your name", "introduce yourself"}:
        speak("I am RK AI, your personal assistant created by RK Innovators.")
    elif cmd in {"help", "help me", "what can you do"}:
        speak("I can help with music playback, alarms, time, date, and basic commands. For more features, connect to the internet.")
    elif cmd in {"commands", "list commands", "available commands"}:
        speak("I support greetings, music controls, time and date queries, alarms, and system commands. Ask me anything!")
    
    # Nice responses
    elif cmd in {"nice", "great", "awesome", "cool", "wonderful", "excellent", "perfect"}:
        responses = ["Thank you!", "Glad you liked it!", "Great to hear!", "Awesome!"]
        speak(random.choice(responses))
    
    else:
        speak(_offline_response(None))


def _offline_response(text: Optional[str]) -> str:
    idx = int(time.time()) % len(OFFLINE_AI_RESPONSES)
    return OFFLINE_AI_RESPONSES[idx]


def offline_ai_reply(text: str) -> str:
    return _offline_response(text)

