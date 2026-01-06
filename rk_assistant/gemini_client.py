"""
Gemini API client for intent classification.
Uses Gemini to classify user intents and return structured JSON.
"""

from __future__ import annotations

import json
from typing import Dict, Any, Optional, List

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("[gemini] google-generativeai not installed. Run: pip install google-generativeai")


# System prompt for intent classification (from backend)
SYSTEM_PROMPT = """
You are RK AI's intent classifier. Your job is to convert a user message into strict tool instructions.
Output must be a pure JSON array of one or more intent objects (no prose, no markdown).

INTENTS
- image: generate images, pictures, posters, thumbnails, art.
- video: generate videos, clips, shorts, episodes, edits, animations.
- docx: write essays, reports, study notes as a .docx.
- ppt: create slide decks or presentations.
- note: short notes or explanations.
- planner: study schedule, daily routine, checklist.
- timetable: school/coaching timetable.
- task: alarms, reminders, todos (use alarm intent for time-based alarms).
- alarm: set alarms with specific times (extract time from prompt).
- announcement: make announcements, broadcast messages, notify.
- period_bell, lesson_plan, exam_paper, grading_sheet, class_planner, teacher_note, weather, news, chat, general, shutdown/exit, music.

STRICT CLASSIFICATION RULES
1) If the user uses generative verbs (generate/make/create/render/build) with a media noun:
   - Mentions video nouns (video/clip/short/episode/animation): intent = "video".
   - Mentions image nouns (image/picture/photo/thumbnail/poster/art): intent = "image".
   - Mentions slides/ppt/presentation: intent = "ppt".
   - Mentions document/report/essay/study notes: intent = "docx".
   Never default to "chat" if a generative intent is implied.
2) If the user says play/start music/song/background sound → intent = "music" (NOT video).
3) If the user says "announce", "announcement", "broadcast", "notify everyone" → intent = "announcement".
4) If the user says "set alarm", "wake me up at", "alarm for [time]" → intent = "alarm" and extract time.
5) If the user mixes multiple requests, return multiple intents in a single array.
6) If the message is truly unclear, use "general".
7) For alarms: extract "time" parameter in format like "8:00 AM", "20:00", etc.
8) For announcements: put the announcement message in the "prompt" parameter.
9) For weather/news, default location to Delhi, India unless user gives a real place; for news, only India.
10) Stop/silence/cancel alarms → intent = "stop_alarm".
11) "emergency", "fire", "evacuate", "alert" → "emergency_alarm" or "fire_alarm".
12) Viva/interview/yourself/oral questions → "chat".
13) Output must be pure JSON; do not wrap in markdown; no commentary.


OUTPUT SCHEMA
[
  {
    "intent": "image" | "video" | "docx" | "ppt" | "note" | "planner" | "timetable" | "task" | "alarm" | "announcement" | "status" | "period_bell" | "assignment" | "exam_paper" | "grading_sheet" | "class_planner" | "teacher_note" | "weather" | "news" | "chat" | "general" | "shutdown/exit" | "music",
    "parameters": {
      "prompt": "description or command",
      "location": "use Delhi, India if not provided for weather/news",
      "note_type": "if notes or summary",
      "time": "if scheduling/alarm (e.g., '8:00 AM', '20:00')",
      "extra": "any additional context"
    }
  }
]

EXAMPLES
User: "generate a video of a dancing pizza"
[
  { "intent": "video", "parameters": { "prompt": "dancing pizza video" } }
]
User: "make a poster for school science fair"
[
  { "intent": "image", "parameters": { "prompt": "school science fair poster" } }
]
User: "create slides on photosynthesis"
[
  { "intent": "ppt", "parameters": { "prompt": "photosynthesis slides" } }
]
User: "write a report on AI ethics"
[
  { "intent": "docx", "parameters": { "prompt": "AI ethics report" } }
]
User: "play lo-fi music"
[
  { "intent": "music", "parameters": { "prompt": "play lo-fi music" } }
]
User: "announce that dinner is ready"
[
  { "intent": "announcement", "parameters": { "prompt": "dinner is ready" } }
]
User: "set alarm for 8 AM"
[
  { "intent": "alarm", "parameters": { "prompt": "wake up", "time": "8:00 AM" } }
]

Now only output JSON following the schema and rules."""


def configure_gemini(api_key: str) -> bool:
    """Configure Gemini API with the provided key."""
    if not GEMINI_AVAILABLE:
        return False
    
    try:
        genai.configure(api_key=api_key)
        return True
    except Exception as e:
        print(f"[gemini] Configuration error: {e}")
        return False


def classify_intent(text: str, api_key: Optional[str] = None, backup_key: Optional[str] = None, model_name: str = "gemini-2.0-flash-exp") -> List[Dict[str, Any]]:
    """
    Classify user intent using Gemini with automatic backup key failover.
    
    Args:
        text: User's query/command
        api_key: Primary Gemini API key
        backup_key: Backup Gemini API key (used if primary fails)
        model_name: Gemini model to use
        
    Returns:
        List of intent objects with 'intent' and 'parameters' fields
    """
    if not GEMINI_AVAILABLE:
        print("[gemini] Library not available, defaulting to chat intent")
        return [{"intent": "chat", "parameters": {"prompt": text}}]
    
    # Try with primary key first
    keys_to_try = []
    if api_key:
        keys_to_try.append(("primary", api_key))
    if backup_key:
        keys_to_try.append(("backup", backup_key))
    
    if not keys_to_try:
        print("[gemini] No API keys provided, defaulting to chat")
        return [{"intent": "chat", "parameters": {"prompt": text}}]
    
    last_error = None
    
    for key_type, key in keys_to_try:
        try:
            # Configure API
            configure_gemini(key)
            
            # Create model instance
            model = genai.GenerativeModel(model_name)
            
            # Build prompt
            full_prompt = f"{SYSTEM_PROMPT}\n\nUser: \"{text}\""
            
            # Generate classification
            print(f"[gemini] Classifying with {key_type} key: '{text}'", flush=True)
            response = model.generate_content(full_prompt)
            
            if not response or not response.text:
                print(f"[gemini] Empty response from {key_type} key")
                last_error = "Empty response"
                continue
            
            raw_response = response.text.strip()
            print(f"[gemini] Raw response ({key_type}): {raw_response[:200]}", flush=True)
            
            # Remove markdown code blocks if present
            if raw_response.startswith("```json"):
                raw_response = raw_response.replace("```json", "").replace("```", "").strip()
            elif raw_response.startswith("```"):
                raw_response = raw_response.replace("```", "").strip()
            
            # Parse JSON
            try:
                intents = json.loads(raw_response)
                
                if not isinstance(intents, list):
                    print(f"[gemini] Response not a list, wrapping: {intents}")
                    intents = [intents]
                
                # Validate intent objects
                for intent_obj in intents:
                    if not isinstance(intent_obj, dict) or "intent" not in intent_obj:
                        print(f"[gemini] Invalid intent object: {intent_obj}")
                        last_error = "Invalid intent format"
                        raise ValueError("Invalid intent object")
                
                print(f"[gemini] ✓ Successfully classified with {key_type} key: {intents}", flush=True)
                return intents
                
            except (json.JSONDecodeError, ValueError) as e:
                print(f"[gemini] Parse error with {key_type} key: {e}")
                last_error = str(e)
                continue
            
        except Exception as e:
            error_msg = str(e)
            print(f"[gemini] Error with {key_type} key: {error_msg}", flush=True)
            last_error = error_msg
            continue
    
    # All keys failed
    print(f"[gemini] All API keys failed. Last error: {last_error}. Defaulting to chat.")
    return [{"intent": "chat", "parameters": {"prompt": text}}]


def get_conversational_response(text: str, api_key: Optional[str] = None, model_name: str = "gemini-2.0-flash-exp") -> str:
    """
    Get conversational response from Gemini for chat/general intents.
    
    Args:
        text: User's message
        api_key: Gemini API key
        model_name: Gemini model to use
        
    Returns:
        Conversational response string
    """
    if not GEMINI_AVAILABLE:
        return "I'm having trouble connecting right now."
    
    try:
        if api_key:
            configure_gemini(api_key)
        
        model = genai.GenerativeModel(model_name)
        
        # Context-aware prompt for voice responses
        system_context = """You are RK AI created by RK Innovators, a helpful voice assistant.
Respond conversationally in 1-2 sentences maximum (optimized for voice/speech).
Be friendly, natural, and concise."""
        
        full_prompt = f"{system_context}\n\nUser: {text}"
        
        print(f"[gemini] Getting conversational response for: '{text}'", flush=True)
        response = model.generate_content(full_prompt)
        
        if not response or not response.text:
            return "I didn't understand that."
        
        reply = response.text.strip()
        print(f"[gemini] Chat response: '{reply}'", flush=True)
        return reply
        
    except Exception as e:
        print(f"[gemini] Chat error: {e}", flush=True)
        return "Sorry, I couldn't process that."


def test_gemini_connection(api_key: str) -> bool:
    """Test if Gemini API is working with the provided key."""
    if not GEMINI_AVAILABLE:
        print("[gemini] Library not available")
        return False
    
    try:
        configure_gemini(api_key)
        model = genai.GenerativeModel("gemini-2.0-flash-exp")
        response = model.generate_content("Say 'Hello' if you can hear me.")
        return bool(response and response.text)
    except Exception as e:
        print(f"[gemini] Connection test failed: {e}")
        return False
