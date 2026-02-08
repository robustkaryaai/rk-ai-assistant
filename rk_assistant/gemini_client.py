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



from .config import GEMINI_MODEL_PRIMARY, GEMINI_MODEL_FALLBACK

def transcribe_audio(audio_bytes: bytes, api_key: Optional[str] = None) -> str:
    """Transcribe audio using Gemini Flash (Native Audio) with RK bias."""
    if not GEMINI_AVAILABLE: return ""
    
    # 1. Try Primary Key
    key = api_key
    client = genai.Client(api_key=key, http_options={'timeout': 10000})

    try:
        from google.genai import types
        response = client.models.generate_content(
            model=GEMINI_MODEL_PRIMARY,
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
                "Transcribe exactly what is said. If no speech, return empty string."
            ],
            config=types.GenerateContentConfig(
                system_instruction="You are RK AI. Expect the user to say 'RK' or 'Arkay' or 'Okay' at the start. Transcribe 'RK' or 'Arkay' as 'RK'.",
                temperature=0.0
            )
        )
        text = response.text.strip() if response.text else ""
        # Fix common misinterpretations of RK
        if text.lower().startswith(("okay", "hi", "hey", "arkay", "arche")):
             # Simple heuristic: if it's short and starts with misinterpretation
             if len(text.split()) < 4:
                 text = text.replace("Okay", "RK").replace("Hi", "RK").replace("Hey", "RK").replace("Arkay", "RK")
        return text
    except Exception as e:
        print(f"[gemini] Transcription failed: {e}")
        return ""


def classify_intent(text: str, api_key: Optional[str] = None, backup_key: Optional[str] = None, model_name: str = GEMINI_MODEL_PRIMARY) -> List[Dict[str, Any]]:
    """
    Classify user intent using Gemini (google-genai SDK 1.0+) with automatic backup key AND model failover.
    """
    if not GEMINI_AVAILABLE:
        print("[gemini] Library not available, defaulting to chat intent")
        return [{"intent": "chat", "parameters": {"prompt": text}}]
    
    # Strategy: Try Primary Model with all keys, then Fallback Model with all keys
    attempts = []
    
    # 1. Primary Model (e.g., gemini-2.5-flash)
    if api_key: attempts.append((model_name, "primary", api_key))
    if backup_key: attempts.append((model_name, "backup", backup_key))
    
    # 2. Fallback Model (e.g., gemma-3-12b-it) - ONLY if default model was requested
    if model_name == GEMINI_MODEL_PRIMARY and GEMINI_MODEL_FALLBACK:
        if api_key: attempts.append((GEMINI_MODEL_FALLBACK, "primary_fallback", api_key))
        if backup_key: attempts.append((GEMINI_MODEL_FALLBACK, "backup_fallback", backup_key))
    
    if not attempts:
        print("[gemini] No API keys provided, defaulting to chat")
        return [{"intent": "chat", "parameters": {"prompt": text}}]
    
    last_error = None
    
    for current_model, key_type, key in attempts:
        try:
            # Create SDK Client with 15s timeout
            client = genai.Client(api_key=key, http_options={'timeout': 15000})
            
            # Build prompt
            full_prompt = f"{SYSTEM_PROMPT}\n\nUser: \"{text}\""
            
            # Generate classification with HARD 15s timeout
            print(f"[gemini] 🚀 Calling {current_model} ({key_type} key)...", flush=True)
            
            import threading
            result_holder = {"response": None, "error": None}
            
            def _call_gemini():
                try:
                    result_holder["response"] = client.models.generate_content(
                        model=current_model,
                        contents=full_prompt
                    )
                except Exception as e:
                    result_holder["error"] = e
            
            thread = threading.Thread(target=_call_gemini, daemon=True)
            thread.start()
            thread.join(timeout=15.0)  # Hard 15s cutoff
            
            if thread.is_alive():
                print(f"[gemini] ⚠️ {key_type} key timed out (SDK retrying internally)", flush=True)
                last_error = "Timeout"
                continue
            
            if result_holder["error"]:
                raise result_holder["error"]
            
            response = result_holder["response"]
            
            if not response or not response.text:
                print(f"[gemini] Empty response from {key_type}")
                last_error = "Empty response"
                continue
            
            raw_response = response.text.strip()
            # print(f"[gemini] Raw response: {raw_response[:200]}", flush=True) # Silenced per user request
            
            # Remove markdown code blocks
            if raw_response.startswith("```json"):
                raw_response = raw_response.replace("```json", "").replace("```", "").strip()
            elif raw_response.startswith("```"):
                raw_response = raw_response.replace("```", "").strip()
            
            # Parse JSON
            try:
                intents = json.loads(raw_response)
                
                if not isinstance(intents, list):
                    intents = [intents]
                
                # Simple validation
                for intent_obj in intents:
                    if not isinstance(intent_obj, dict) or "intent" not in intent_obj:
                        raise ValueError("Invalid intent object")
                
                print(f"[gemini] ✓ Success with {current_model} ({key_type})", flush=True)
                return intents
                
            except (json.JSONDecodeError, ValueError) as e:
                print(f"[gemini] Parse error ({current_model}): {e}")
                last_error = str(e)
                continue
            
        except Exception as e:
            error_msg = str(e)
            print(f"[gemini] Error ({current_model}): {error_msg}", flush=True)
            last_error = error_msg
            continue
    
    # All attempts failed
    print(f"[gemini] All models/keys failed. Last error: {last_error}. Defaulting to chat.")
    return [{"intent": "chat", "parameters": {"prompt": text}}]


def get_conversational_response(text: str, api_key: Optional[str] = None, model_name: str = GEMINI_MODEL_PRIMARY) -> str:
    """
    Get conversational response from Gemini with model fallback.
    """
    if not GEMINI_AVAILABLE:
        return "I'm having trouble connecting right now."
    
    # Strategy: Try Primary Model, then Fallback Model
    attempts = []
    if api_key:
        attempts.append((model_name, "primary", api_key))
        if model_name == GEMINI_MODEL_PRIMARY and GEMINI_MODEL_FALLBACK:
            attempts.append((GEMINI_MODEL_FALLBACK, "fallback", api_key))

    if not attempts:
        return "I need an API key to chat."

    for current_model, key_type, key in attempts:
        try:
            client = genai.Client(api_key=key, http_options={'timeout': 15000})
            
            # Context-aware prompt
            from .memory_engine import retrieve_memories
            memories = retrieve_memories(text)
            memory_context = ""
            if memories:
                memory_list = "\n".join([f"- {m}" for m in memories])
                memory_context = f"\n\nContext from Memory:\n{memory_list}\nUse this context if relevant."
                print(f"[gemini] Injected {len(memories)} memories.", flush=True)

            system_context = f"""You are RK AI created by RK Innovators, a helpful voice assistant.
Respond conversationally in 1-2 sentences maximum (optimized for voice/speech).
Be friendly, natural, and concise.{memory_context}"""
            
            prompt = f"{system_context}\n\nUser: {text}\n\nAssistant:"
            
            # Generate
            print(f"[gemini] 💬 Chatting with {current_model}...", flush=True)
            
            import threading
            result_holder = {"response": None, "error": None}
            
            def _call_gemini():
                try:
                    result_holder["response"] = client.models.generate_content(
                        model=current_model,
                        contents=prompt
                    )
                except Exception as e:
                    result_holder["error"] = e
            
            thread = threading.Thread(target=_call_gemini, daemon=True)
            thread.start()
            thread.join(timeout=15.0)
            
            if thread.is_alive():
               continue
            
            if result_holder["error"]:
                raise result_holder["error"]
            
            response = result_holder["response"]
            
            if not response or not response.text:
                continue
            
            reply = response.text.strip()
            print(f"[gemini] Chat response: '{reply}'", flush=True)
            return reply
            
        except Exception as e:
            print(f"[gemini] Chat error ({current_model}): {e}", flush=True)
            continue

    return "Sorry, I couldn't process that."


def test_gemini_connection(api_key: str) -> bool:
    """Test if Gemini API is working with the provided key using new SDK."""
    if not GEMINI_AVAILABLE:
        print("[gemini] Library not available")
        return False
    
    try:
        # Add 15s timeout to prevent massive hangs if network/key is broken
        client = genai.Client(api_key=api_key, http_options={'timeout': 15000})
        
        # Hard 15s process-level timeout
        import threading
        result_holder = {"response": None, "error": None}
        
        def _test():
            try:
                result_holder["response"] = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents="Say 'Hello' if you can hear me."
                )
            except Exception as e:
                result_holder["error"] = e
        
        thread = threading.Thread(target=_test, daemon=True)
        thread.start()
        thread.join(timeout=15.0)
        
        if thread.is_alive():
            print("[gemini] Connection test timed out after 15s")
            return False
        
        if result_holder["error"]:
            raise result_holder["error"]
        
        return bool(result_holder["response"] and result_holder["response"].text)
    except Exception as e:
        print(f"[gemini] Connection test failed: {e}")
        return False
