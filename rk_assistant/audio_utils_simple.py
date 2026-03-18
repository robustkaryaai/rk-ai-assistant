"""
Simple audio utilities - just what we need.
"""
import subprocess
import socket
import os
import hashlib
import re
from pathlib import Path


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
    # Use hash of text as filename to avoid filesystem issues
    text_hash = hashlib.md5(text.encode()).hexdigest()
    filename = f"{text_hash}.mp3"
    
    # Check pre-generated cache first (instant!)
    pregenerated = PREGENERATED_CACHE / filename
    if pregenerated.exists():
        return pregenerated
    
    # Fall back to runtime cache
    return RUNTIME_CACHE / filename


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
        # Piper -> mpg123 (PulseAudio)
        piper_cmd = [PIPER_EXECUTABLE, "--model", PIPER_VOICE_MODEL, "--output_file", "-"]
        # Use -o pulse for mpg123
        player_cmd = ["mpg123", "-o", "pulse", "-q", "-"]
        
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


def sanitize_text(text):
    """Remove emojis and non-standard symbols."""
    if not text: return ""
    return re.sub(r'[^\w\s,!.?\'\"-]', '', text)


def _split_into_chunks(text: str):

    """Split text into speakable chunks (by newline first, then by sentence)."""
    chunks = []
    for line in text.split('\n'):
        line = line.strip().lstrip('- ').strip()
        if not line:
            continue
        # Split long lines at sentence boundaries
        parts = re.split(r'(?<=[.!?])\s+', line)
        for part in parts:
            part = part.strip()
            if part:
                chunks.append(part)
    return chunks


def _speak_chunk(text: str, alsa_device: str = "pulse") -> bool:
    """Speak a single chunk of text. Returns True if gTTS succeeded."""
    cache_path_mp3 = _get_cache_path(text)
    cache_path_wav = cache_path_mp3.with_suffix('.wav')

    # WAV cached → instant
    if cache_path_wav.exists():
        subprocess.run(['aplay', '-D', alsa_device, '-q', str(cache_path_wav)],
                       check=False, stderr=subprocess.DEVNULL, timeout=30)
        return True

    # MP3 cached → convert & play
    if cache_path_mp3.exists():
        subprocess.run(['mpg123', '-w', str(cache_path_wav), str(cache_path_mp3)],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if cache_path_wav.exists():
            subprocess.run(['aplay', '-D', alsa_device, '-q', str(cache_path_wav)],
                           check=False, stderr=subprocess.DEVNULL, timeout=30)
            return True

    # Neither cached → generate via gTTS
    try:
        from gtts import gTTS
        import threading

        def _generate():
            # Use Indian English TLD to properly pronounce Hinglish words (deshbhakti etc)
            tts = gTTS(text=text, lang='en', tld='co.in')
            tts.save(str(cache_path_mp3))

        gen_thread = threading.Thread(target=_generate)
        gen_thread.start()
        gen_thread.join(timeout=12)  # 12s per chunk (reasonable for short sentence)

        if gen_thread.is_alive():
            print(f"⚠ gTTS chunk timed out, using espeak for: {text[:40]}", flush=True)
            return False

        subprocess.run(['mpg123', '-w', str(cache_path_wav), str(cache_path_mp3)],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if cache_path_wav.exists():
            subprocess.run(['aplay', '-D', alsa_device, '-q', str(cache_path_wav)],
                           check=False, stderr=subprocess.DEVNULL, timeout=30)
            return True
    except Exception as e:
        print(f"⚠ gTTS chunk failed: {e}", flush=True)

    return False


def speak(text, use_gtts=True):
    """
    Convert text to speech with intelligent cascading fallback.
    Long text is split into sentence chunks and played sequentially.
    """
    try:
        text = sanitize_text(text)
        if not text:
            return
            
        print(f"🔊 {text}", flush=True)
        alsa_device = "pulse"
        
        # Check online status ONCE for the entire speech session
        online = is_online() if use_gtts else False

        # 1. Try Piper (Offline, High Quality)
        if _is_piper_available():
            if _speak_with_piper(text):
                return
            print("⚠ Piper failed, falling back...", flush=True)

        # 2. Split into chunks for gTTS or espeak
        if len(text) < 150:
            chunks = [text]
        else:
            chunks = _split_into_chunks(text)
            if not chunks:
                chunks = [text]

        for chunk in chunks:
            if not chunk:
                continue
            
            spoken = False
            # Use the status we checked at the beginning to avoid mixing engines
            if online:
                spoken = _speak_chunk(chunk, alsa_device)
            
            if not spoken:
                # espeak fallback for this chunk (always works, robotic)
                # Use a slightly more natural espeak voice if possible
                subprocess.run(['espeak', '-v', 'en-us+f2', '-s', '150', chunk], 
                               check=False, stderr=subprocess.DEVNULL)

    except Exception as e:
        print(f"⚠ Speak error: {e}", flush=True)


