"""
Tiny ML Intent Classifier for Offline Commands.

This module replaces exact string matching with a blazing-fast Machine Learning
model (TF-IDF + LinearSVC) that trains instantaneously on boot and infers
intents in <1ms. This allows off-the-cuff variations of offline commands 
to work reliably without querying Gemini.
"""

import time
import pickle
import os
from pathlib import Path

# Add a try-except to gently degrade if scikit-learn is missing
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.svm import LinearSVC
    from sklearn.pipeline import make_pipeline
    _ML_AVAILABLE = True
except ImportError:
    _ML_AVAILABLE = False
    print("[intent] Warning: scikit-learn not installed. Offline intent classification will use basic string matching.")

# Ensure package context
current_dir = os.path.dirname(os.path.abspath(__file__))

# Where to cache the compiled model so we don't have to train it every single boot
MODEL_CACHE_PATH = os.path.join(current_dir, "data", "intent_model.pkl")

# Define our training dataset
# Format: intent_id -> list of sample phrases
TRAINING_DATA = {
    # System Controls
    "volume_up": ["volume up", "louder", "make it louder", "turn it up", "increase volume", "speak louder"],
    "volume_down": ["volume down", "quieter", "make it quieter", "turn it down", "decrease volume", "be quiet", "shh"],
    "mute": ["mute", "silence", "shut up", "turn off sound"],
    "unmute": ["unmute", "turn on sound", "restore volume"],
    "stop": ["stop", "cancel", "halt", "pause", "stop talking", "abort"],
    "restart_device": ["restart device", "reboot system", "rk reboot", "rk restart"],
    "shutdown_device": ["shutdown device", "power off", "rk shutdown", "go to sleep forever"],
    "update_system": ["update system", "rk update", "pull latest code"],
    
    # Music & Media
    "play_music": ["play music", "start playing", "resume music", "play something"],
    "pause_music": ["pause music", "pause playback"],
    "next_song": ["next song", "skip track", "play the next one"],
    "previous_song": ["previous song", "go back", "play last track"],
    "play_again": ["play again", "replay", "restart song", "repeat"],
    
    # Information
    "time": ["what time is it", "tell me the time", "current time", "clock"],
    "date": ["what is the date", "what day is it", "today's date", "date"],
    "weather": ["what is the weather", "weather report", "is it raining", "temperature outside", "weather forecast"],
    "news": ["what is the news", "tell me the headlines", "read the news", "latest updates"],
    "battery": ["battery level", "how much battery is left", "battery status"],
    
    # Conversations
    "greeting": ["hello", "hi", "hey", "good morning", "good evening", "greetings"],
    "how_are_you": ["how are you", "how are things", "what's up", "how's it going"],
    "gratitude": ["thank you", "thanks a lot", "many thanks", "I appreciate it"],
    "goodbye": ["goodbye", "bye", "see you later", "catch you later"],
    "identity": ["who are you", "what is your name", "introduce yourself", "tell me about yourself"],
    "joke": ["tell me a joke", "make me laugh", "say something funny"],
    
    # Utilities & Hardware
    "set_alarm": ["set an alarm", "wake me up", "create an alarm", "set a timer"],
    "task": ["remind me", "create a task", "new reminder", "add to my to do list"],
    "bluetooth_connect": ["connect bluetooth", "pair speaker", "turn on bluetooth"],
    "bluetooth_disconnect": ["disconnect bluetooth", "unpair speaker", "turn off bluetooth"],
    "test_connection": ["test connection", "are you online", "check internet", "diagnostic check", "diagnostics"]
}

# The global cached pipeline
_intent_pipeline = None

def _train_model():
    """Trains the TF-IDF + LinearSVC model from scratch."""
    if not _ML_AVAILABLE:
        return None
        
    print("[intent] Training Tiny ML Intent Model...")
    start_time = time.time()
    
    X_train = []
    y_train = []
    
    for intent, phrases in TRAINING_DATA.items():
        for phrase in phrases:
            X_train.append(phrase.lower())
            y_train.append(intent)
            
    # LinearSVC is incredibly fast for text classification on edge devices
    # TF-IDF converts phrases to mathematical word-frequency vectors
    pipeline = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2)), # Look at single words and pairs of words
        LinearSVC(C=1.0, dual="auto")        # Fast SVM
    )
    
    pipeline.fit(X_train, y_train)
    
    duration = time.time() - start_time
    print(f"[intent] Model trained on {len(X_train)} phrases in {duration:.3f}s")
    
    # Cache it to disk
    try:
        os.makedirs(os.path.dirname(MODEL_CACHE_PATH), exist_ok=True)
        with open(MODEL_CACHE_PATH, 'wb') as f:
            pickle.dump(pipeline, f)
    except Exception as e:
        print(f"[intent] Warning: Could not cache model to disk: {e}")
        
    return pipeline

def get_intent_pipeline():
    """Returns the trained model pipeline, loading from cache if available."""
    global _intent_pipeline
    
    if not _ML_AVAILABLE:
        return None
        
    if _intent_pipeline is not None:
        return _intent_pipeline
        
    if os.path.exists(MODEL_CACHE_PATH):
        try:
            with open(MODEL_CACHE_PATH, 'rb') as f:
                _intent_pipeline = pickle.load(f)
            return _intent_pipeline
        except Exception:
            pass # Fallback to training
            
    _intent_pipeline = _train_model()
    return _intent_pipeline

def classify_local_intent(text: str, confidence_threshold=0.45) -> str | None:
    """
    Classifies a transcribed string into a specific offline intent.
    Returns the intent_id if confident, or None if it's too obscure.
    """
    if not text or len(text.strip()) < 2:
        return None
        
    text = text.lower().strip()
    
    if not _ML_AVAILABLE:
        # Fallback to primitive matching if sklearn fails to load
        for intent, phrases in TRAINING_DATA.items():
            if any(p in text for p in phrases):
                return intent
        return None

    pipeline = get_intent_pipeline()
    if not pipeline: return None
    
    # Make prediction
    predicted_intent = pipeline.predict([text])[0]
    
    # We must check confidence. LinearSVC doesn't natively output probabilities 
    # via predict_proba, but we can look at the decision function margin.
    decision_scores = pipeline.decision_function([text])[0]
    
    # Get the max score (highest confidence margin)
    try:
        max_score = max(decision_scores)
    except TypeError:
        # If binary classification, decision_function returns a single float
        max_score = abs(decision_scores)
    
    if max_score < confidence_threshold:
        return None
        
    # SAFETY LOCK: Prevent ambient noise from fatally manipulating the Pi
    # TF-IDF can occasionally hallucinate on random short audio static.
    # We require strict keyword presence for system termination commands.
    if predicted_intent in ["shutdown_device", "restart_device", "update_system"]:
        required_words = ["shutdown", "restart", "reboot", "power off", "update"]
        if not any(w in text for w in required_words):
            print(f"[intent] 🛑 Blocked false-positive fatal system command: '{text}' -> {predicted_intent}")
            return None
            
    return predicted_intent

# Legacy functions preserved for backwards compatibility with main.py online routing
def guess_fallback_intent(text: str) -> dict | None:
    """
    Guess intent from text when backend response is empty.
    Returns a dict matching the expected JSON output format, or None.
    """
    if not text: return None
    text_lower = text.lower()
    params = {"prompt": text}
    
    gen_verbs = ["generate", "make", "create", "render", "build"]
    video_nouns = ["video", "clip", "short", "episode", "animation", "edit"]
    image_nouns = ["image", "picture", "photo", "thumbnail", "poster", "art"]
    ppt_nouns = ["slide", "slides", "ppt", "presentation", "deck"]
    docx_nouns = ["document", "report", "essay", "note", "study note"]
    
    has_gen_verb = any(v in text_lower for v in gen_verbs)
    if has_gen_verb:
        if any(n in text_lower for n in video_nouns): return {"intent": "video", "parameters": params}
        if any(n in text_lower for n in image_nouns): return {"intent": "image", "parameters": params}
        if any(n in text_lower for n in ppt_nouns): return {"intent": "ppt", "parameters": params}
        if any(n in text_lower for n in docx_nouns):
            if "note" in text_lower: return {"intent": "note", "parameters": params}
            return {"intent": "docx", "parameters": params}

    if "play" in text_lower or "start" in text_lower:
        if any(m in text_lower for m in ["music", "song", "sound", "radio"]):
            return {"intent": "music", "parameters": params}

    if "alarm" in text_lower:
        if any(w in text_lower for w in ["stop", "silence", "cancel", "quiet"]):
            return {"intent": "stop_alarm", "parameters": params}
        return {"intent": "task", "parameters": params}

    if "remember" in text_lower or "memorize" in text_lower:
        return {"intent": "remember", "parameters": params}

    if any(w in text_lower for w in ["emergency", "fire", "evacuate", "alert"]):
        return {"intent": "emergency_alarm", "parameters": params}
        
    return {"intent": "general", "parameters": params}

def start_pending_request_msg(intent: str) -> str:
    mapping = {
        "image": "an image", "video": "a video", "ppt": "a presentation",
        "docx": "a document", "note": "a note", "music": "music", "task": "a task",
    }
    thing = mapping.get(intent, "your request")
    return f"I have requested the server for {thing}. Please check the RK app for further response."

def needs_backend(text: str) -> bool:
    if not text: return False
    text_lower = text.lower()
    
    gen_verbs = ["generate", "make", "create", "render", "build", "produce"]
    if not any(verb in text_lower for verb in gen_verbs):
        return False
    
    video_keywords = ["video", "clip", "short", "episode", "animation", "edit", "movie", "film"]
    image_keywords = ["image", "picture", "photo", "thumbnail", "poster", "art", "drawing", "illustration"]
    ppt_keywords = ["slide", "slides", "ppt", "presentation", "deck", "powerpoint"]
    docx_keywords = ["document", "report", "essay", "paper", "docx", "word", "doc"]
    text_file_keywords = ["text file", "txt file", "save to file", "write to file"]
    
    return (
        any(k in text_lower for k in video_keywords) or
        any(k in text_lower for k in image_keywords) or
        any(k in text_lower for k in ppt_keywords) or
        any(k in text_lower for k in docx_keywords) or
        any(k in text_lower for k in text_file_keywords)
    )
