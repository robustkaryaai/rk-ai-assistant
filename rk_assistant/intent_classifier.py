"""
Simple keyword-based intent classifier for fallback scenarios.
Implements the user's specific rules for images, video, music, etc.
"""

def guess_fallback_intent(text: str) -> dict | None:
    """
    Guess intent from text when backend response is empty.
    Returns a dict matching the expected JSON output format, or None.
    """
    if not text:
        return None
        
    text_lower = text.lower()
    
    # helper for parameters
    params = {"prompt": text}
    
    # 1. Generative verbs + Media nouns
    gen_verbs = ["generate", "make", "create", "render", "build"]
    video_nouns = ["video", "clip", "short", "episode", "animation", "edit"]
    image_nouns = ["image", "picture", "photo", "thumbnail", "poster", "art"]
    ppt_nouns = ["slide", "slides", "ppt", "presentation", "deck"]
    docx_nouns = ["document", "report", "essay", "note", "study note"]
    
    # Check for generative intent
    has_gen_verb = any(v in text_lower for v in gen_verbs)
    
    if has_gen_verb:
        if any(n in text_lower for n in video_nouns):
            return {"intent": "video", "parameters": params}
        if any(n in text_lower for n in image_nouns):
            return {"intent": "image", "parameters": params}
        if any(n in text_lower for n in ppt_nouns):
            return {"intent": "ppt", "parameters": params}
        if any(n in text_lower for n in docx_nouns):
            # If notes specifically mentioned
            if "note" in text_lower:
                 return {"intent": "note", "parameters": params}
            return {"intent": "docx", "parameters": params}

    # 2. Music (play/start music/song)
    if "play" in text_lower or "start" in text_lower:
        if any(m in text_lower for m in ["music", "song", "sound", "radio"]):
            return {"intent": "music", "parameters": params}

    # 3. Alarms
    if "alarm" in text_lower:
        if any(w in text_lower for w in ["stop", "silence", "cancel", "quiet"]):
            return {"intent": "stop_alarm", "parameters": params}
        return {"intent": "task", "parameters": params} # task covers alarms usually

    # 4. Emergency
    if any(w in text_lower for w in ["emergency", "fire", "evacuate", "alert"]):
        return {"intent": "emergency_alarm", "parameters": params}
        
    # 5. General / Chat
    # If no specific media intent recognized but it was a command, default to chat/general
    return {"intent": "general", "parameters": params}

def start_pending_request_msg(intent: str) -> str:
    """Return the speech response for a pending request."""
    # "if user said gen image and server gave no response say i have requested the server for an image pls check rk app for further resposne"
    
    mapping = {
        "image": "an image",
        "video": "a video",
        "ppt": "a presentation",
        "docx": "a document",
        "note": "a note",
        "music": "music",
        "task": "a task",
    }
    
    thing = mapping.get(intent, "your request")
    return f"I have requested the server for {thing}. Please check the RK app for further response."
