"""
Simple audio utilities - just what we need.
"""
import pyttsx3

# Initialize TTS engine once
_engine = None

def _get_engine():
    """Lazy init TTS engine."""
    global _engine
    if _engine is None:
        _engine = pyttsx3.init()
        _engine.setProperty('rate', 150)
    return _engine


def speak(text):
    """
    Convert text to speech using pyttsx3 (offline, reliable).
    """
    try:
        print(f"🔊 {text}", flush=True)
        engine = _get_engine()
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"⚠ Speak error: {e}", flush=True)
