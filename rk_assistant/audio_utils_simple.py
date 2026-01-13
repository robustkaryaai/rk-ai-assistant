"""
Simple audio utilities - just what we need.
"""
import subprocess
import socket
import os
import hashlib
from pathlib import Path


# Cache directory for gTTS audio files
CACHE_DIR = Path.home() / ".cache" / "rk_tts"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def is_online():
    """Quick check if internet is available."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except:
        return False


def _get_cache_path(text):
    """Get cache file path for given text."""
    # Use hash of text as filename to avoid filesystem issues
    text_hash = hashlib.md5(text.encode()).hexdigest()
    return CACHE_DIR / f"{text_hash}.mp3"


def speak(text, use_gtts=True):
    """
    Convert text to speech.
    Uses gTTS with caching for fast responses (~200ms for cached).
    Falls back to espeak if offline or gTTS fails.
    """
    try:
        print(f"🔊 {text}", flush=True)
        
        # Use gTTS with caching when online
        if use_gtts and is_online():
            try:
                cache_path = _get_cache_path(text)
                
                # Check if already cached
                if cache_path.exists():
                    # Play cached audio (super fast ~200ms)
                    subprocess.run(['mpg123', '-q', str(cache_path)], check=False, stderr=subprocess.DEVNULL)
                    return
                
                # Not cached, generate and cache
                from gtts import gTTS
                
                tts = gTTS(text=text, lang='en')
                tts.save(str(cache_path))
                
                # Play the newly cached audio
                subprocess.run(['mpg123', '-q', str(cache_path)], check=False, stderr=subprocess.DEVNULL)
                return
                
            except Exception as e:
                print(f"⚠ gTTS failed, falling back to espeak: {e}", flush=True)
        
        # Fallback to espeak (offline or gTTS disabled)
        subprocess.run(['espeak', text], check=False, stderr=subprocess.DEVNULL)
        
    except Exception as e:
        print(f"⚠ Speak error: {e}", flush=True)

