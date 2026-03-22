"""
Gemini API client for intent classification.
Uses Gemini to classify user intents and return structured JSON.
"""

from __future__ import annotations

import json
import time
from typing import Dict, Any, Optional, List, Tuple

from .config import (
    GEMINI_AVAILABLE,
    GEMINI_API_KEY,
    GEMINI_API_KEY_BACKUP,
    GEMINI_MODEL_PRIMARY,
    GEMINI_MODEL_FALLBACK,
    SLUG_FILE,
)

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("[gemini] google-genai not installed. Run: pip install google-genai")
except Exception:
    GEMINI_AVAILABLE = False

# Load device slug for prompt injection
def _get_device_slug():
    try:
        with open(SLUG_FILE, "r") as f:
            return f.read().strip().split(":")[0]
    except:
        return "UNKNOWN"

DEVICE_ID = _get_device_slug()


def _build_key_chain(
    api_key: Optional[str] = None,
    backup_key: Optional[str] = None,
) -> List[Tuple[str, str]]:
    keys_to_try: List[Tuple[str, str]] = []
    primary = api_key or GEMINI_API_KEY
    secondary = backup_key or GEMINI_API_KEY_BACKUP
    if primary:
        keys_to_try.append(("primary", primary))
    if secondary and secondary != primary:
        keys_to_try.append(("backup", secondary))
    return keys_to_try


def _build_model_chain(
    model_name: Optional[str] = None,
    fallback_model: Optional[str] = None,
) -> List[str]:
    primary_model = (model_name or GEMINI_MODEL_PRIMARY or "gemini-3.1-flash-lite-preview").strip()
    secondary_model = (fallback_model or GEMINI_MODEL_FALLBACK or "").strip()
    models_to_try = [primary_model]
    if secondary_model and secondary_model != primary_model:
        models_to_try.append(secondary_model)
    return models_to_try

# System prompt for intent classification (from backend)
SYSTEM_PROMPT = """
You are RK AI's intent classifier and response generator. Your job is to convert a user message into strict tool instructions and a natural spoken response.
Your physical hardware ID is {DEVICE_ID}. If the user asks for your ID, serial number, or identity code, you MUST provide this exact number in your spoken reply.
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
- period_bell, lesson_plan, exam_paper, grading_sheet, class_planner, teacher_note, weather, news, chat, general, shutdown/exit, music, cozy_setup, focus_mode, open_app, lumina_coding.

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
12) If the user says "make my setup cozy", "prepare coding environment", "open workspace" → intent = "cozy_setup".
13) If the user says "activate focus mode", "don't disturb", "focus time" → intent = "focus_mode".
14) If the user says "open [app name]", "launch [app name]" → intent = "open_app" and put app name in "app_name" parameter.
15) If the user is starting a coding session on Lumina OS / Lumina (e.g. "I'm coming to code on Lumina", "prepare my Lumina workspace", "set up Lumina for coding", "I'm coming for coding") → intent = "lumina_coding". Optional parameters: folder (path), ide (app name).
16) If the user says "turn the computer off", "shut down the desktop", "power off my PC" → intent = "shutdown/exit".
17) Output must be pure JSON; do not wrap in markdown; no commentary.

RESPONSE GENERATION (reply field)
- For EVERY intent, generate a short, natural, and helpful spoken response in the "reply" field.
- Do NOT use generic phrases like "Got it" or "I will make it".
- Be specific and conversational. E.g., for "make a video of a cat", say "Sure, I'll start generating a video of a playful cat for you."
- For "tell me a joke", say "Here's a funny one for you!" followed by the joke in the same string or as a separate "chat" intent.

OUTPUT SCHEMA
[
  {
    "intent": "image" | "video" | "docx" | "ppt" | "note" | "planner" | "timetable" | "task" | "alarm" | "announcement" | "status" | "period_bell" | "assignment" | "exam_paper" | "grading_sheet" | "class_planner" | "teacher_note" | "weather" | "news" | "chat" | "general" | "shutdown/exit" | "music" | "cozy_setup" | "focus_mode" | "open_app" | "lumina_coding",
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
User: "I'm coming to code on Lumina, prep my space"
[
  { "intent": "lumina_coding", "reply": "On it — I'll brighten your space and wake your desktop for Lumina.", "parameters": { "prompt": "prepare Lumina coding workspace" } }
]
User: "turn the computer off"
[
  { "intent": "shutdown/exit", "reply": "Okay, I'll shut the computer down.", "parameters": { "prompt": "turn the computer off" } }
]

Now only output JSON following the schema and rules. """.replace("{DEVICE_ID}", str(DEVICE_ID))


def classify_intent(
    text: str,
    api_key: Optional[str] = None,
    backup_key: Optional[str] = None,
    model_name: Optional[str] = None,
    fallback_model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Classify user intent using Gemini (google-genai SDK 1.0+) with automatic backup key and model failover.
    
    Args:
        text: User's query/command
        api_key: Primary Gemini API key
        backup_key: Backup Gemini API key (used if primary fails)
        model_name: Primary Gemini model to use
        fallback_model: Fallback Gemini model (used if primary model fails/times out)
    """
    prompt_text = str(text or "").strip()
    if prompt_text:
        print(f"[gemini] User: {prompt_text}", flush=True)

    if not GEMINI_AVAILABLE:
        print("[gemini] Library not available, defaulting to chat intent")
        return [{"intent": "chat", "parameters": {"prompt": prompt_text}}]
    
    keys_to_try = _build_key_chain(api_key=api_key, backup_key=backup_key)
    if not keys_to_try:
        print("[gemini] No API keys provided, defaulting to chat")
        return [{"intent": "chat", "parameters": {"prompt": prompt_text}}]

    models_to_try = _build_model_chain(model_name=model_name, fallback_model=fallback_model)
    
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
                    
                    # 🚀 Lowered timeout for faster failover/response
                    client = genai.Client(api_key=key, http_options={'timeout': 15000}) 
                    full_prompt = f"{SYSTEM_PROMPT}\n\nUser: \"{prompt_text}\""
                    
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
    return [{"intent": "chat", "parameters": {"prompt": prompt_text}}]


def get_conversational_response(
    text: str,
    api_key: Optional[str] = None,
    backup_key: Optional[str] = None,
    model_name: Optional[str] = None,
    fallback_model: Optional[str] = None,
) -> str:
    """
    Get conversational response from Gemini for chat/general intents.
    """
    if not GEMINI_AVAILABLE:
        return "I'm having trouble connecting right now."

    keys_to_try = _build_key_chain(api_key=api_key, backup_key=backup_key)
    models_to_try = _build_model_chain(model_name=model_name, fallback_model=fallback_model)
    if not keys_to_try:
        return "I'm having trouble connecting right now."

    try:
        from .memory_engine import retrieve_memories, get_recent_chats

        memories = retrieve_memories(text)
        memory_context = ""
        if memories:
            memory_list = "\n".join([f"- {m}" for m in memories])
            memory_context = f"\n\nContext from Memory:\n{memory_list}\nUse this context if relevant to the user's query."
            print(f"[gemini] Injected {len(memories)} memories into context.", flush=True)

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
    except Exception:
        prompt = f"You are RK AI created by RK Innovators, a helpful voice assistant.\n\nUser: {text}\n\nAssistant:\n"

    last_error = None
    for key_type, key in keys_to_try:
        for current_model in models_to_try:
            try:
                client = genai.Client(api_key=key, http_options={'timeout': 12000})

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
                thread.join(timeout=18.0)

                if thread.is_alive():
                    last_error = f"{current_model} timed out"
                    print(f"[gemini] Chat timeout with {current_model} ({key_type} key)", flush=True)
                    continue

                if result_holder["error"]:
                    raise result_holder["error"]

                response = result_holder["response"]
                if not response or not response.text:
                    last_error = f"Empty response from {current_model}"
                    print(f"[gemini] Chat empty response from {current_model} ({key_type} key)", flush=True)
                    continue

                reply = response.text.strip()
                print(f"[gemini] Chat response via {current_model} ({key_type} key): '{reply}'", flush=True)
                return reply
            except Exception as e:
                last_error = str(e)
                print(f"[gemini] Chat error with {current_model} ({key_type} key): {e}", flush=True)
                continue

    print(f"[gemini] Chat failed across all keys/models. Last error: {last_error}", flush=True)
    return "Sorry, I couldn't process that."


def transcribe_audio(audio_bytes: bytes, api_key: str) -> str:
    """Transcribe audio using Gemini Flash (Experimental)."""
    if not GEMINI_AVAILABLE:
        return ""
    try:
        client = genai.Client(api_key=api_key)
        # Gemini can take raw bytes if wrapped correctly
        response = client.models.generate_content(
            model="gemini-1.5-flash-8b",
            contents=[
                "Transcribe this audio. Output only the transcribed text.",
                {"mime_type": "audio/wav", "data": audio_bytes}
            ]
        )
        return response.text.strip() if response and response.text else ""
    except Exception as e:
        print(f"[gemini-stt] Error: {e}")
        return ""

def parse_smart_home_command(
    text: str,
    api_key: Optional[str] = None,
    backup_key: Optional[str] = None,
) -> Optional[Tuple[bool, str, Optional[str]]]:
    """
    Small LLM pass for natural smart-home phrasing when rules miss the device target.
    Returns (on?, device_phrase_or_ALL, color_or_None) or None.
    """
    if not GEMINI_AVAILABLE or not text or not str(text).strip():
        return None
    keys = [k for k in (api_key, backup_key) if k]
    if not keys:
        return None
    prompt = (
        "You parse smart-home voice commands. Reply with ONLY valid JSON, no markdown:\n"
        '{"action":"on"|"off","target":"short English device name or ALL for whole home",'
        '"color":null|"red"|"blue"|"green"|"yellow"|"purple"|"white"|"warm"|"cool"}\n'
        f'Utterance: {json.dumps(text.strip())}'
    )
    for key in keys:
        try:
            client = genai.Client(api_key=key, http_options={"timeout": 10000})
            response = client.models.generate_content(
                model=GEMINI_MODEL_PRIMARY,
                contents=prompt,
            )
            raw = (response.text or "").strip()
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()
            data = json.loads(raw)
            act = str(data.get("action", "")).lower()
            if act not in ("on", "off"):
                continue
            tgt = data.get("target") or ""
            tgt = str(tgt).strip()
            if not tgt:
                continue
            col = data.get("color")
            col = str(col).lower().strip() if col else None
            if col in ("none", "null", ""):
                col = None
            return (act == "on", tgt, col)
        except Exception as e:
            print(f"[gemini] smart_home parse: {e}", flush=True)
            continue
    return None


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
