"""
Simple audio utilities - just what we need.
"""
import os
import subprocess
import threading
import time
import hashlib
from pathlib import Path
from typing import List, Optional

# One TTS at a time — avoids ALSA/Pulse fights with STT and stacked gTTS downloads.
_tts_lock = threading.Lock()
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

def sanitize_text(text: str) -> str:
    """Clean up text for better TTS results."""
    return text.replace('*', '').replace('_', '').replace('`', '').strip()

def _split_into_chunks(text: str) -> List[str]:
    """Split text into sentences or manageable chunks for TTS."""
    import re
    sentences = re.split(r'(?<=[.!?]) +', text)
    return [s for s in sentences if s.strip()]

def _speak_with_gtts(text: str, alsa_device: str = "pulse") -> bool:
    """Standard Online TTS using Google TTS - Nuked and Rewritten for maximum reliability."""
    import hashlib
    import os
    import subprocess
    from pathlib import Path
    
    # 1. Setup paths
    hash_val = hashlib.md5(text.encode()).hexdigest()
    mp3_path = CACHE_DIR / f"gtts_{hash_val}.mp3"
    wav_path = CACHE_DIR / f"gtts_{hash_val}.wav"

    # 2. Check Cache First
    if wav_path.exists():
        try:
            subprocess.run(['paplay', '--device', alsa_device, str(wav_path)], check=True, timeout=15)
            return True
        except Exception as e:
            print(f"[gtts] Cache play failed: {e}")

    try:
        from gtts import gTTS
        
        # 3. Download from Google (with retry)
        success = False
        for attempt in range(2):
            try:
                # Pre-clean the path to avoid Permission Denied if owned by root
                if mp3_path.exists():
                    try: os.remove(str(mp3_path))
                    except: pass
                
                print(f"[gtts] fetch (attempt {attempt + 1}) len={len(text)}", flush=True)
                tts = gTTS(text=text, lang='en', slow=False)
                tts.save(str(mp3_path))
                
                # Set permissions to 666 so anyone can read/write it
                try: os.chmod(str(mp3_path), 0o666)
                except: pass
                
                if mp3_path.exists() and mp3_path.stat().st_size > 0:
                    success = True
                    break
            except Exception as e:
                print(f"[gtts] Download attempt {attempt+1} failed: {e}")
                time.sleep(1)

        if not success:
            return False

        # 4. Try Direct MP3 Playback (Fastest fallback)
        try:
            # Try mpg123
            res = subprocess.run(['mpg123', '-q', '-a', alsa_device, str(mp3_path)], timeout=20)
            if res.returncode == 0:
                # Convert in background for future WAV cache
                subprocess.Popen(['ffmpeg', '-y', '-i', str(mp3_path), str(wav_path)], 
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
        except Exception as e:
            print(f"[gtts] mpg123 failed: {e}")

        # 5. Convert to WAV (Standard reliable method)
        try:
            subprocess.run(['ffmpeg', '-y', '-i', str(mp3_path), str(wav_path)], 
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=15)
            
            if wav_path.exists():
                subprocess.run(['paplay', '--device', alsa_device, str(wav_path)], check=True, timeout=15)
                return True
        except Exception as e:
            print(f"[gtts] ffmpeg/paplay failed: {e}")

        # 6. Final Stand: use 'play' from sox
        try:
            subprocess.run(['play', '-q', str(mp3_path)], timeout=20)
            return True
        except Exception as e:
            print(f"[gtts] sox play failed: {e}")

    except Exception as e:
        print(f"[gtts] Fatal Rewrite Error: {e}")
    finally:
        # Cleanup mp3 if wav exists
        if mp3_path.exists() and wav_path.exists():
            try: os.remove(str(mp3_path))
            except: pass
    
    return False

def speak(text: str, online: bool = True, allow_network_tts: bool = True):
    """
    Main TTS entry point. Piper → (optional gTTS if allow_network_tts) → espeak.
    allow_network_tts=False for command poller / scans — no repeated Google hits.
    """
    text = sanitize_text(text)
    if not text:
        return

    with _tts_lock:
        print(f"🔊 {text}", flush=True)
        alsa_device = "pulse"

        try:
            subprocess.run(['pacmd', 'list-sinks'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        except Exception:
            pass

        if _is_piper_available():
            try:
                if _speak_with_piper(text, alsa_device):
                    return
            except Exception as e:
                print(f"[tts] Piper failed: {e}")

        if allow_network_tts and online and not FORCE_OFFLINE:
            try:
                if _speak_with_gtts(text, alsa_device):
                    return
            except Exception as e:
                print(f"[tts] gTTS failed: {e}")

        if allow_network_tts:
            print("[tts] preferred engines failed — espeak fallback", flush=True)
        else:
            print("[tts] offline chain (piper skipped/failed) — espeak", flush=True)
        try:
            subprocess.run(['espeak', '-s', '160', '-v', 'en-us', text], check=False, timeout=15)
        except Exception as e:
            print(f"[tts] espeak failed: {e}", flush=True)
