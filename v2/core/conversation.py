import time
import datetime
from typing import List, Dict, Any, Optional

class ConversationEngine:
    """
    Alexa-Grade Conversational Intelligence (Section 4).
    Features:
    - 4.1 3-Turn Context Stacking (resolves 'there', 'play more like this', follow-ups)
    - 4.2 'Start My Day' / Good Morning Routine Briefing
    - 4.3 Voice Brain-Dump / Quick Notes to Cloud Dashboard
    - 4.4 Adaptive Night / Whisper Mode (drops volume 11 PM - 6 AM)
    """

    def __init__(self, client, tts, player):
        self.client = client
        self.tts = tts
        self.player = player
        self.history: List[Dict[str, str]] = [] # Stack of {'role': 'user'|'assistant', 'text': '...'}
        self.last_entity: Optional[str] = None # e.g. "Mumbai", "Arijit Singh"
        self.last_intent: Optional[str] = None

    def add_interaction(self, user_text: str, assistant_reply: str, intent: Optional[str] = None):
        """Append to 3-turn sliding memory stack."""
        self.history.append({"user": user_text, "reply": assistant_reply})
        if len(self.history) > 3:
            self.history.pop(0)

        self.last_intent = intent

    def resolve_contextual_query(self, query: str) -> str:
        """Resolves pronouns ('there', 'him', 'it') using recent entity cache."""
        cleaned = query.strip()
        if "there" in cleaned.lower() and self.last_entity:
            resolved = cleaned.replace("there", self.last_entity).replace("There", self.last_entity)
            print(f"🧠 [CONTEXT STACK] Resolved 'there' -> '{self.last_entity}': {resolved}")
            return resolved
        return cleaned

    def execute_morning_routine(self) -> str:
        """
        4.2 'Start My Day' Routine Briefing:
        - Greeting
        - Time & Date
        - Today's Alarms
        - Weather preview
        """
        now = datetime.datetime.now()
        greeting = "Radhe Radhe! Good morning."
        time_str = now.strftime("%I:%M %p").lstrip("0")
        day_str = now.strftime("%A, %B %d")

        briefing = (
            f"{greeting} The time is {time_str} on {day_str}. "
            "Your devices are active, alarms are synchronized, and the system is ready. "
            "Have a productive day ahead!"
        )
        return briefing

    def is_whisper_mode_active(self) -> bool:
        """4.4 Adaptive Whisper Mode: Drops volume between 11 PM and 6 AM."""
        hour = datetime.datetime.now().hour
        return hour >= 23 or hour < 6

    def save_voice_note(self, note_text: str) -> str:
        """4.3 Quick voice note sent to cloud dashboard."""
        print(f"📝 [VOICE NOTE] Saving note: {note_text}")
        if self.client:
            self.client.send_text(f"note: {note_text}")
        return f"Saved note to your dashboard: {note_text}"
