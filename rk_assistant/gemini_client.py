"""
Gemini API client for intent classification.
Uses Gemini to classify user intents and return structured JSON.
"""

from __future__ import annotations

import json
from typing import Dict, Any, Optional, List

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("[gemini] google-genai not installed. Run: pip install google-genai")


# System prompt for intent classification (from backend)
SYSTEM_PROMPT = """
You are RK AI's intent classifier and response generator. Your job is to convert a user message into strict tool instructions and a natural spoken response.
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
1) Generative intents (image, video, docx, ppt, note, planner, timetable, lesson_plan, exam_paper, grading_sheet, class_planner, teacher_note) MUST ONLY be triggered if the user EXPLICITLY uses a verb like "make", "generate", "create", "build", "write", "render", or "prepare". 
   - If the user just mentions the topic (e.g., "tell me about photosynthesis" or "photosynthesis essay"), use "chat" or "general".
   - If the user says "make a report on photosynthesis", then use "docx".
2) If the user says play/start music/song/background sound → intent = "music".
3) If the user says "announce", "announcement", "broadcast", "notify everyone" → intent = "announcement".
4) If the user says "set alarm", "wake me up at", "alarm for [time]" → intent = "alarm" and extract time.
5) If the user mixes multiple requests, return multiple intents in a single array.
6) For alarms: extract "time" parameter in format like "8:00 AM", "20:00", etc.
7) For announcements: put the announcement message in the "prompt" parameter.
8) For weather/news, default location to Delhi, India unless user gives a real place; for news, only India.
9) Stop/silence/cancel alarms → intent = "stop_alarm".
10) "emergency", "fire", "evacuate", "alert" → "emergency_alarm" or "fire_alarm".
11) Viva/interview/yourself/oral questions → "chat".
12) Output must be pure JSON; do not wrap in markdown; no commentary.

RESPONSE GENERATION (reply field)
- For EVERY intent, generate a short, natural, and helpful spoken response in the "reply" field.
- Do NOT use generic phrases like "Got it" or "I will make it".
- Be specific and conversational. E.g., for "make a video of a cat", say "Sure, I'll start generating a video of a playful cat for you."
- For "tell me a joke", say "Here's a funny one for you!" followed by the joke in the same string or as a separate "chat" intent.

OUTPUT SCHEMA
[
  {
    "intent": "image" | "video" | "docx" | "ppt" | "note" | "planner" | "timetable" | "task" | "alarm" | "announcement" | "status" | "period_bell" | "assignment" | "exam_paper" | "grading_sheet" | "class_planner" | "teacher_note" | "weather" | "news" | "chat" | "general" | "shutdown/exit" | "music",
    "reply": "Natural spoken response to the user",
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
  { "intent": "video", "reply": "Coming right up! I'm rendering a video of a dancing pizza for you.", "parameters": { "prompt": "dancing pizza video" } }
]
User: "tell me about space"
[
  { "intent": "chat", "reply": "Space is vast and fascinating! It's mostly a vacuum, containing billions of galaxies, each with billions of stars and planets. What specific part of space would you like to know about?", "parameters": { "prompt": "tell me about space" } }
]
User: "make a poster for school science fair"
[
  { "intent": "image", "reply": "I'll create a professional poster for your school science fair right now.", "parameters": { "prompt": "school science fair poster" } }
]

Now only output JSON following the schema and rules. """


def classify_intent(text: str, api_key: Optional[str] = None, backup_key: Optional[str] = None, model_name: str = "gemma-3-12b-it", fallback_model: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Classify user intent using Gemini (google-genai SDK 1.0+) with automatic backup key and model failover.
    
    Args:
        text: User's query/command
        api_key: Primary Gemini API key
        backup_key: Backup Gemini API key (used if primary fails)
        model_name: Primary Gemini model to use
        fallback_model: Fallback Gemini model (used if primary model fails/times out)
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
    
    models_to_try = [model_name]
    if fallback_model and fallback_model != model_name:
        models_to_try.append(fallback_model)
    
    last_error = None
    MAX_503_RETRIES = 2  # Keep low — flash is only 5 RPM
    RETRY_WAITS = [5, 10]  # seconds between retries
    # Nested loop: Try each KEY, and for each key, try each MODEL
    for key_type, key in keys_to_try:
        for current_model in models_to_try:
            for attempt in range(MAX_503_RETRIES + 1):  # 0..3
                try:
                    if attempt > 0:
                        wait = 2 ** attempt  # 2s, 4s, 8s
                        print(f"[gemini] 🔄 503 retry {attempt}/{MAX_503_RETRIES} for {current_model}, waiting {wait}s...", flush=True)
                        time.sleep(wait)
                    
                    print(f"[gemini] 🚀 Calling {current_model} ({key_type} key)...", flush=True)
                    
                    client = genai.Client(api_key=key, http_options={'timeout': 180000})
                    full_prompt = f"{SYSTEM_PROMPT}\n\nUser: \"{text}\""
                    
                    response = client.models.generate_content(
                        model=current_model,
                        contents=full_prompt
                    )
                    
                    if not response or not response.text:
                        print(f"[gemini] Empty response from {key_type} key")
                        last_error = "Empty response"
                        break  # Try next model/key
                    
                    raw_response = response.text.strip()
                    print(f"[gemini] Raw response ({key_type}): {raw_response[:200]}", flush=True)
                    
                    if raw_response.startswith("```json"):
                        raw_response = raw_response.replace("```json", "").replace("```", "").strip()
                    elif raw_response.startswith("```"):
                        raw_response = raw_response.replace("```", "").strip()
                    
                    try:
                        intents = json.loads(raw_response)
                        if not isinstance(intents, list):
                            intents = [intents]
                        for intent_obj in intents:
                            if not isinstance(intent_obj, dict) or "intent" not in intent_obj:
                                last_error = "Invalid intent format"
                                raise ValueError("Invalid intent object")
                        print(f"[gemini] ✓ Classified with {current_model} ({key_type} key): {intents}", flush=True)
                        return intents
                    except (json.JSONDecodeError, ValueError) as e:
                        print(f"[gemini] Parse error: {e}")
                        last_error = str(e)
                        break  # Parse error, try next model
                        
                except Exception as e:
                    error_msg = str(e)
                    is_503 = "503" in error_msg or "UNAVAILABLE" in error_msg
                    print(f"[gemini] Error with {current_model} ({key_type}): {error_msg[:80]}", flush=True)
                    last_error = error_msg
                    if is_503 and attempt < MAX_503_RETRIES:
                        continue  # Retry same model/key
                    break  # Non-503 or retries exhausted → next model/key
    
    print(f"[gemini] All attempts failed. Last error: {last_error[:80]}. Defaulting to chat.")
    return [{"intent": "chat", "parameters": {"prompt": text}}]


def get_conversational_response(text: str, api_key: Optional[str] = None, model_name: str = "gemma-3-12b-it") -> str:
    """
    Get conversational response from Gemini for chat/general intents.
    """
    if not GEMINI_AVAILABLE:
        return "I'm having trouble connecting right now."
    
    try:
        # Create SDK Client with 15s timeout
        client = genai.Client(api_key=api_key, http_options={'timeout': 180000})
        
        # Context-aware prompt for voice responses
        from .memory_engine import retrieve_memories, get_recent_chats
        
        # 1. Retrieve relevant memories (RAG)
        memories = retrieve_memories(text)
        memory_context = ""
        if memories:
            memory_list = "\n".join([f"- {m}" for m in memories])
            memory_context = f"\n\nContext from Memory:\n{memory_list}\nUse this context if relevant to the user's query."
            print(f"[gemini] Injected {len(memories)} memories into context.", flush=True)

        # 2. Retrieve last 10 chats for conversation continuity
        recent_chats = get_recent_chats(limit=10)
        chat_context = ""
        if recent_chats:
            chat_list = "\n".join([f"User: {c['user']}\nAI: {c['ai']}" for c in recent_chats])
            chat_context = f"\n\nRecent Conversation History:\n{chat_list}"
            print(f"[gemini] Injected {len(recent_chats)} recent chats into context.", flush=True)

        system_context = f"""You are RK AI created by RK Innovators, a helpful voice assistant.
Keep your responses conversational and natural, optimized for voice/speech. Be brief for casual chat, but if the user asks for a poem, story, or detailed explanation, provide the full complete answer.{memory_context}{chat_context}"""
        
        prompt = f"{system_context}\n\nUser: {text}\n\nAssistant:\
"
        
        # Hard 15s timeout
        import threading
        result_holder = {"response": None, "error": None}
        
        def _call_gemini():
            try:
                result_holder["response"] = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
            except Exception as e:
                result_holder["error"] = e
        
        thread = threading.Thread(target=_call_gemini, daemon=True)
        thread.start()
        thread.join(timeout=180.0)
        
        if thread.is_alive():
            print("[gemini] Chat timed out after 15s", flush=True)
            return "I'm taking too long to respond. Please try again."
        
        if result_holder["error"]:
            raise result_holder["error"]
        
        response = result_holder["response"]
        
        if not response or not response.text:
            return "I didn't understand that."
        
        reply = response.text.strip()
        print(f"[gemini] Chat response: '{reply}'", flush=True)
        return reply
        
    except Exception as e:
        print(f"[gemini] Chat error: {e}", flush=True)
        return "Sorry, I couldn't process that."


def test_gemini_connection(api_key: str) -> bool:
    """Test if Gemini API is working with the provided key using new SDK."""
    if not GEMINI_AVAILABLE:
        print("[gemini] Library not available")
        return False
    
    try:
        # Add 15s timeout to prevent massive hangs if network/key is broken
        client = genai.Client(api_key=api_key, http_options={'timeout': 180000})
        
        # Hard 15s process-level timeout
        import threading
        result_holder = {"response": None, "error": None}
        
        def _test():
            try:
                result_holder["response"] = client.models.generate_content(
                    model="gemma-3-12b-it",
                    contents="Say 'Hello' if you can hear me."
                )
            except Exception as e:
                result_holder["error"] = e
        
        thread = threading.Thread(target=_test, daemon=True)
        thread.start()
        thread.join(timeout=180.0)
        
        if thread.is_alive():
            print("[gemini] Connection test timed out after 15s")
            return False
        
        if result_holder["error"]:
            raise result_holder["error"]
        
        return bool(result_holder["response"] and result_holder["response"].text)
    except Exception as e:
        print(f"[gemini] Connection test failed: {e}")
        return False
