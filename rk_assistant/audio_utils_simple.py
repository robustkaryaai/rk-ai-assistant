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


def _is_piper_available():
    """Check if Piper TTS is installed and configured."""
    try:
        from .config import PIPER_EXECUTABLE, PIPER_VOICE_MODEL
        
        # Check if executable exists
        if not Path(PIPER_EXECUTABLE).exists():
            return False
        
        # Check if voice model exists
        if not Path(PIPER_VOICE_MODEL).exists():
            return False
        
        return True
    except:
        return False


def _speak_with_piper(text):
    """
    Synthesize speech using Piper TTS.
    Returns True if successful, False otherwise.
    """
    try:
        from .config import PIPER_EXECUTABLE, PIPER_VOICE_MODEL
        
        # Generate audio with Piper (outputs to stdout)
        # piper --model <model> --output_file <file> or pipe to player
        # For speed, we pipe directly to mpg123
        piper_cmd = [PIPER_EXECUTABLE, "--model", PIPER_VOICE_MODEL, "--output_file", "-"]
        player_cmd = ["mpg123", "-q", "-"]
        
        # Run Piper and pipe to mpg123
        piper_proc = subprocess.Popen(
            piper_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        
        player_proc = subprocess.Popen(
            player_cmd,
            stdin=piper_proc.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Send text to Piper
        piper_proc.stdin.write(text.encode())
        piper_proc.stdin.close()
        
        # Wait for completion
        piper_proc.wait()
        player_proc.wait()
        
        return piper_proc.returncode == 0
        
    except Exception as e:
        print(f"⚠ Piper TTS failed: {e}", flush=True)
        return False


def speak(text, use_gtts=True):
    """
    Convert text to speech with intelligent cascading fallback.
    
    Priority:
    1. Piper TTS (natural voice, ~200-800ms, offline)
    2. gTTS cache (natural voice, ~200ms, cached phrases)
    3. espeak (robotic voice, ~50ms, always works)
    """
    try:
        print(f"🔊 {text}", flush=True)
        
        # Try Piper TTS first (natural voice, fast, offline)
        if _is_piper_available():
            if _speak_with_piper(text):
                return
            print("⚠ Piper failed, trying gTTS cache...", flush=True)
        
        # Fallback to gTTS with caching when online
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
        
        # Final fallback to espeak (offline or gTTS disabled)
        subprocess.run(['espeak', text], check=False, stderr=subprocess.DEVNULL)
        
    except Exception as e:
        print(f"⚠ Speak error: {e}", flush=True)


