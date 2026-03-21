"""
Simple audio utilities - just what we need.
"""
import os
import subprocess
import time
import hashlib
from pathlib import Path
from typing import List, Optional
from .config import CACHE_DIR, FORCE_OFFLINE, GROQ_API_KEY, BASE_DIR

def _get_cache_path(text: str) -> Path:
    """Generate a unique cache path for a given text string."""
    hash_val = hashlib.md5(text.encode()).hexdigest()
    return CACHE_DIR / f"tts_{hash_val}.wav"

def _is_piper_available() -> bool:
    """Check if Piper TTS is installed on the system."""
    return os.path.exists("/usr/bin/piper") or os.path.exists("/usr/local/bin/piper")

def _speak_with_piper(text: str, alsa_device: str = "pulse") -> bool:
    """Ultra-fast Offline TTS using Piper."""
    cache_path = _get_cache_path(text)
    if not cache_path.exists():
        try:
            # 🚀 Piper generates speech at ~10x realtime on Pi Zero
            model_path = BASE_DIR.parent / "models" / "en_US-lessac-medium.onnx"
            if not model_path.exists():
                return False
                
            cmd = f'echo "{text}" | piper --model {str(model_path)} --output_file {str(cache_path)}'
            subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"[piper] Error: {e}")
            return False

    if cache_path.exists():
        try:
            # Added timeout to prevent hanging if Bluetooth is flaky
            subprocess.run(['paplay', '--device', alsa_device, str(cache_path)], check=False, timeout=30)
            return True
        except:
            return False
    return False

def _speak_with_groq(text: str, alsa_device: str = "pulse") -> bool:
    """Fast Online TTS using Groq (OpenAI-compatible)."""
    if not GROQ_API_KEY:
        return False
        
    cache_path = _get_cache_path(text)
    if cache_path.exists():
        subprocess.run(['paplay', '--device', alsa_device, str(cache_path)], check=False)
        return True

    try:
        import requests
        url = "https://api.groq.com/openai/v1/audio/speech"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        data = {
            "model": "tts-1", # Assuming Groq TTS model name
            "input": text,
            "voice": "alloy"
        }
        
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        if resp.ok:
            with open(cache_path, "wb") as f:
                f.write(resp.content)
            subprocess.run(['paplay', '--device', alsa_device, str(cache_path)], check=False)
            return True
    except Exception as e:
        print(f"[groq-tts] Error: {e}")
    return False

def sanitize_text(text: str) -> str:
    """Clean up text for better TTS results."""
    return text.replace('*', '').replace('_', '').replace('`', '').strip()

def _split_into_chunks(text: str) -> List[str]:
    """Split text into sentences or manageable chunks for TTS."""
    import re
    sentences = re.split(r'(?<=[.!?]) +', text)
    return [s for s in sentences if s.strip()]

def _speak_with_gtts(text: str, alsa_device: str = "pulse") -> bool:
    """Standard Online TTS using Google TTS."""
    cache_path = _get_cache_path(text)
    if cache_path.exists():
        subprocess.run(['paplay', '--device', alsa_device, str(cache_path)], check=False)
        return True

    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang='en')
        # Save to a temporary mp3 then convert to wav for paplay, or just use mpg123
        temp_mp3 = cache_path.with_suffix('.mp3')
        tts.save(str(temp_mp3))
        
        # Convert to wav for paplay (more reliable on Pi)
        subprocess.run(['ffmpeg', '-y', '-i', str(temp_mp3), str(cache_path)], 
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        
        if cache_path.exists():
            subprocess.run(['paplay', '--device', alsa_device, str(cache_path)], check=False)
            if temp_mp3.exists(): os.remove(temp_mp3)
            return True
    except Exception as e:
        print(f"[gtts] Error: {e}")
    return False

def speak(text: str, online: bool = True):
    """
    Main TTS entry point. Uses Piper (Offline), Groq (Fast Online), or gTTS (Fallback Online).
    """
    text = sanitize_text(text)
    if not text: return
    
    print(f"🔊 {text}", flush=True)
    alsa_device = "pulse"

    # 🚀 Step 1: Force PulseAudio to refresh sink list
    try:
        subprocess.run(['pacmd', 'list-sinks'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
    except:
        pass

    # 🚀 Step 2: Try Piper (Instant Offline)
    if _is_piper_available():
        if _speak_with_piper(text, alsa_device):
            return

    # 🚀 Step 3: Try Groq (Fast Online)
    if online and not FORCE_OFFLINE:
        if _speak_with_groq(text, alsa_device):
            return

    # 🚀 Step 4: Try gTTS (Standard Online Fallback)
    if online and not FORCE_OFFLINE:
        if _speak_with_gtts(text, alsa_device):
            return
            
    # Emergency Offline Fallback
    subprocess.run(['espeak', '-v', 'en-us', text], check=False)
