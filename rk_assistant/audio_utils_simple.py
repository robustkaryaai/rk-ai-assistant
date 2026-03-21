"""
Simple audio utilities - just what we need.
"""
import os
import subprocess
import time
import hashlib
from pathlib import Path
from typing import List, Optional
from .config import CACHE_DIR, FORCE_OFFLINE, GROQ_API_KEY

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
            model_path = "/home/raspberrypi/rk-ai-assistant-main/models/en_US-lessac-medium.onnx"
            if not os.path.exists(model_path):
                return False
                
            cmd = f'echo "{text}" | piper --model {model_path} --output_file {cache_path}'
            subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"[piper] Error: {e}")
            return False

    if cache_path.exists():
        subprocess.run(['paplay', '--device', alsa_device, str(cache_path)], check=False)
        return True
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

def speak(text: str, online: bool = True):
    """
    Main TTS entry point. Nuked gTTS in favor of Piper (Offline) and Groq (Online).
    Processes full text at once to avoid inter-sentence pauses.
    """
    text = sanitize_text(text)
    if not text: return
    
    print(f"🔊 {text}", flush=True)
    alsa_device = "pulse"

    # 🚀 Step 1: Force PulseAudio to refresh sink list (Fix for silent RK)
    try:
        subprocess.run(['pacmd', 'list-sinks'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass

    # 🚀 Step 2: Try Piper (Instant Offline) - Full Text at once
    if _is_piper_available():
        if _speak_with_piper(text, alsa_device):
            return

    # 🚀 Step 3: Try Groq (Fast Online) - Full Text at once
    if online and not FORCE_OFFLINE:
        if _speak_with_groq(text, alsa_device):
            return
            
    # Emergency Offline Fallback
    subprocess.run(['espeak', '-v', 'en-us', text], check=False)
