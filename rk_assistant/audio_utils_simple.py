"""
Simple audio utilities - just what we need.
"""
import subprocess
import socket
import os
import hashlib
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
    Convert text toto speech with intelligent cascading fallback.
    
    Priority:
    1. Piper TTS (natural voice, ~200-800ms, offline)
    2. gTTS cache (natural voice, ~200ms, cached phrases)
    3. espeak (robotic voice, ~50ms, always works)
    """
    try:
        print(f"🔊 {text}", flush=True)
        
        # Get Bluetooth speaker MAC for bluealsa output
        from .config import BLUETOOTH_SPEAKER_MAC
        # Use the plug plugin to handle format conversions if needed, targeting the specific device
        bluealsa_device = f"bluealsa:DEV={BLUETOOTH_SPEAKER_MAC}"
        
        # Try Piper TTS first (natural voice, fast, offline)
        if _is_piper_available():
            if _speak_with_piper(text):
                return
            print("⚠ Piper failed, trying gTTS cache...", flush=True)
        
        # Fallback to gTTS with caching when online
        if use_gtts and is_online():
            try:
                # We need both MP3 (storage) and WAV (playback) paths
                cache_path_mp3 = _get_cache_path(text)
                cache_path_wav = cache_path_mp3.with_suffix('.wav')
                
                # Check if WAV is already cached (fastest path)
                if cache_path_wav.exists():
                    subprocess.run(['aplay', '-D', bluealsa_device, '-q', str(cache_path_wav)], 
                                 check=False, stderr=subprocess.DEVNULL, timeout=10)
                    return
                
                # If MP3 exists but WAV doesn't, just convert it
                if cache_path_mp3.exists():
                    subprocess.run(['mpg123', '-w', str(cache_path_wav), str(cache_path_mp3)], 
                                 check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if cache_path_wav.exists():
                        subprocess.run(['aplay', '-D', bluealsa_device, '-q', str(cache_path_wav)], 
                                     check=False, stderr=subprocess.DEVNULL, timeout=10)
                        return
                
                # Neither exists - generate new audio
                from gtts import gTTS
                import threading
                
                def _generate():
                    tts = gTTS(text=text, lang='en')
                    tts.save(str(cache_path_mp3))
                
                gen_thread = threading.Thread(target=_generate)
                gen_thread.start()
                gen_thread.join(timeout=10) # 10s hard timeout for gTTS generation
                
                if gen_thread.is_alive():
                    print("⚠ gTTS generation timed out, falling back to espeak", flush=True)
                    raise TimeoutError("gTTS generation took too long")

                # Convert generated MP3 to WAV for aplay
                subprocess.run(['mpg123', '-w', str(cache_path_wav), str(cache_path_mp3)], 
                             check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                # Play the WAV
                if cache_path_wav.exists():
                    subprocess.run(['aplay', '-D', bluealsa_device, '-q', str(cache_path_wav)], 
                                 check=False, stderr=subprocess.DEVNULL, timeout=10)
                return
                
            except Exception as e:
                print(f"⚠ gTTS failed, falling back to espeak: {e}", flush=True)
        
        # Final fallback to espeak
        subprocess.run(['espeak', text], check=False, stderr=subprocess.DEVNULL)
        
    except Exception as e:
        print(f"⚠ Speak error: {e}", flush=True)


