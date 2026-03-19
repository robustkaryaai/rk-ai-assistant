"""
Simple audio utilities - just what we need.
"""
import subprocess
import socket
import os
import hashlib
import re
import threading
import time
from pathlib import Path
from typing import Optional, Dict, List

# Pre-generated audio cache (committed to git, instant playback)
PREGENERATED_CACHE = Path(__file__).parent / "audio_cache"

# Runtime cache directory for new phrases
RUNTIME_CACHE = Path.home() / ".cache" / "rk_tts"
RUNTIME_CACHE.mkdir(parents=True, exist_ok=True)

def is_online():
    """Quick check if internet is available."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except:
        return False

def _get_cache_path(text):
    """Get cache file path for given text, checking pre-generated first."""
    text_hash = hashlib.md5(text.encode()).hexdigest()
    filename = f"{text_hash}.mp3"
    
    pregenerated = PREGENERATED_CACHE / filename
    if pregenerated.exists():
        return pregenerated
    
    return RUNTIME_CACHE / filename

def _is_piper_available():
    """Check if Piper TTS is installed and configured."""
    try:
        from .config import PIPER_EXECUTABLE, PIPER_VOICE_MODEL
        if not Path(PIPER_EXECUTABLE).exists():
            return False
        if not Path(PIPER_VOICE_MODEL).exists():
            return False
        return True
    except:
        return False

def _speak_with_piper(text: str, alsa_device: str = "pulse") -> bool:
    """Speak text using Piper (local). Returns True if successful."""
    try:
        from .config import PIPER_EXECUTABLE, PIPER_VOICE_MODEL
        
        piper_cmd = [PIPER_EXECUTABLE, '--model', str(PIPER_VOICE_MODEL), '--output_raw']
        
        # Start Piper
        piper_proc = subprocess.Popen(
            piper_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        
        # Start paplay (PulseAudio native)
        player_proc = subprocess.Popen(
            ['paplay', '--device', alsa_device, '--raw', '--rate', '22050', '--format', 's16le', '--channels', '1'],
            stdin=piper_proc.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        
        # Send text to Piper
        piper_proc.stdin.write(text.encode())
        piper_proc.stdin.close()
        
        # Wait for Piper to finish
        piper_proc.wait()
        
        # Wait for player and monitor failure
        _, stderr = player_proc.communicate(timeout=60)
        if player_proc.returncode != 0:
            err_msg = stderr.decode() if stderr else 'No error'
            print(f"⚠ paplay (Piper) failed with code {player_proc.returncode}: {err_msg}", flush=True)
            return False
            
        return True
    except Exception as e:
        print(f"⚠ Piper TTS failed: {e}", flush=True)
        return False

def sanitize_text(text):
    """Remove emojis and non-standard symbols."""
    if not text: return ""
    return re.sub(r'[^\w\s,!.?\'\"-]', '', text)

def _split_into_chunks(text: str):
    """Split text into speakable chunks."""
    chunks = []
    for line in text.split('\n'):
        line = line.strip().lstrip('- ').strip()
        if not line:
            continue
        parts = re.split(r'(?<=[.!?])\s+', line)
        for part in parts:
            part = part.strip()
            if part:
                chunks.append(part)
    return chunks

def _speak_chunk(text: str, alsa_device: str = "pulse") -> bool:
    """Speak a single chunk of text. Returns True if successful."""
    cache_path_mp3 = _get_cache_path(text)
    cache_path_wav = cache_path_mp3.with_suffix('.wav')

    # Try playing cached WAV
    if cache_path_wav.exists():
        res = subprocess.run(['paplay', '--device', alsa_device, str(cache_path_wav)],
                             check=False, stderr=subprocess.PIPE, timeout=30)
        if res.returncode == 0:
            return True
        print(f"⚠ paplay failed for cached WAV: {res.stderr.decode() if res.stderr else 'unknown'}", flush=True)

    # Try playing cached MP3 (convert to WAV first)
    if cache_path_mp3.exists():
        subprocess.run(['mpg123', '-w', str(cache_path_wav), str(cache_path_mp3)],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if cache_path_wav.exists():
            res = subprocess.run(['paplay', '--device', alsa_device, str(cache_path_wav)],
                                 check=False, stderr=subprocess.PIPE, timeout=30)
            if res.returncode == 0:
                return True
            print(f"⚠ paplay failed for converted MP3: {res.stderr.decode() if res.stderr else 'unknown'}", flush=True)

    # Generate via gTTS
    try:
        from gtts import gTTS
        def _generate():
            tts = gTTS(text=text, lang='en', tld='co.in')
            tts.save(str(cache_path_mp3))

        gen_thread = threading.Thread(target=_generate)
        gen_thread.start()
        gen_thread.join(timeout=15)

        if gen_thread.is_alive():
            print(f"⚠ gTTS timeout for: {text[:30]}", flush=True)
            return False

        subprocess.run(['mpg123', '-w', str(cache_path_wav), str(cache_path_mp3)],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if cache_path_wav.exists():
            res = subprocess.run(['paplay', '--device', alsa_device, str(cache_path_wav)],
                                 check=False, stderr=subprocess.PIPE, timeout=30)
            return res.returncode == 0
    except Exception as e:
        print(f"⚠ gTTS failed: {e}", flush=True)

    return False

def speak(text, use_gtts=True):
    """Convert text to speech with fallbacks."""
    try:
        text = sanitize_text(text)
        if not text: return
            
        print(f"🔊 {text}", flush=True)
        alsa_device = "pulse"
        online = is_online() if use_gtts else False

        # 1. Piper (Offline)
        if _is_piper_available():
            if _speak_with_piper(text, alsa_device):
                return

        # 2. gTTS (Online)
        if online:
            chunks = _split_into_chunks(text)
            for chunk in chunks:
                _speak_chunk(chunk, alsa_device)
            return
            
        print(f"⚠ TTS Failed: Offline and Piper unavailable.", flush=True)
    except Exception as e:
        print(f"⚠ speak() error: {e}", flush=True)
