"""
Optimized Audio Utilities for Pi Zero W.
Restored Google STT and robust TTS.
"""
import os
import sys
import time
import subprocess
import threading
from pathlib import Path

# Try to import speech_recognition (for Google STT)
try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_AVAILABLE = True
except ImportError:
    sr = None
    SPEECH_RECOGNITION_AVAILABLE = False

# Configuration
from .config import (
    SAMPLE_RATE, 
    CHANNELS, 
    POCKETSPHINX_MODEL_DIR,
    WAKE_WORD,
    LAST_AUDIO,
    BLUETOOTH_SPEAKER_MAC,
    MIC_DEVICE_INDEX
)

# Hardcoded optimal settings for Pi Zero W
# Handle empty MAC gracefully to avoid invalid argument
if BLUETOOTH_SPEAKER_MAC:
    ALSA_DEVICE = f"bluealsa:DEV={BLUETOOTH_SPEAKER_MAC},PROFILE=a2dp"
else:
    ALSA_DEVICE = "default" # Fallback

BUFFER_TIME = "500000" # 0.5s buffer

def play_audio_file(file_path: str):
    """Play WAV file using aplay with optimal buffers."""
    if not os.path.exists(file_path): return
    try:
        subprocess.run(
            ["aplay", "-D", ALSA_DEVICE, "--buffer-time=" + BUFFER_TIME, "-q", file_path],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"[audio] Play error: {e}")

def play_audio_url(url: str):
    """Play MP3 URL using mpg123 directly to BlueALSA."""
    if not url: return None
    try:
        # -a specifies device, -b 1024 is buffer size in KB
        return subprocess.Popen(
            ["mpg123", "-a", ALSA_DEVICE, "-b", "1024", "-q", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except:
        return None

def speak(text):
    """
    Ultra-lightweight TTS.
    1. Piper (if available) -> WAV -> aplay
    2. Espeak (fallback) -> WAV -> aplay
    """
    print(f"🔊 {text}")
    try:
        # Try Piper first (best quality, efficient if model loaded)
        piper_binary = "/usr/local/bin/piper"
        model = os.path.expanduser("~/.local/share/piper/voices/en_US-lessac-medium.onnx")
        
        if os.path.exists(piper_binary) and os.path.exists(model):
            # Pipe piper output directly to aplay to save disk I/O
            # Use 22050Hz for standard piper models, format S16_LE
            cmd = f"{piper_binary} --model {model} --output_raw | aplay -D {ALSA_DEVICE} -r 22050 -f S16_LE -t raw -q"
            subprocess.run(cmd, shell=True)
            return

        # Fallback to espeak
        subprocess.run(
            ["espeak", "-w", "/tmp/tts.wav", text], 
            check=False, stderr=subprocess.DEVNULL
        )
        play_audio_file("/tmp/tts.wav")
        
    except Exception as e:
        print(f"[tts] Error: {e}")

def live_stt_listen(recognizer, mic, timeout=None, phrase_time_limit=None) -> str:
    """
    Restore Google STT (Online).
    """
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return ""
    
    try:
        with mic as source:
            # Short calibration (already done in main, but good to be safe if environment changed)
            # recognizer.adjust_for_ambient_noise(source, duration=0.5) 
            # Listen
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        
        # Transcribe
        try:
            return recognizer.recognize_google(audio)
        except sr.UnknownValueError:
            return ""
        except sr.RequestError:
            return ""
            
    except sr.WaitTimeoutError:
        return "" # Silence
    except Exception as e:
        print(f"[stt] Live listen error: {e}")
        return ""

def online_stt(audio_path: Path) -> str:
    """Transcribe audio file using Google STT."""
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return ""
    if not os.path.exists(audio_path):
        return ""
        
    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(str(audio_path)) as source:
            audio = recognizer.record(source)
        return recognizer.recognize_google(audio)
    except Exception:
        return ""

def record_until_silence(out_path=LAST_AUDIO, silence_duration=2.0) -> Path:
    """
    Record audio using 'arecord' (low CPU) for offline commands.
    Fixed duration for simplicity on Pi Zero (silence detection in python is heavy).
    """
    try:
        # Determine device
        device_arg = "default"
        if MIC_DEVICE_INDEX is not None and MIC_DEVICE_INDEX >= 0:
            device_arg = f"plughw:{MIC_DEVICE_INDEX},0"
        
        # Record 5 seconds fixed (simple & robust)
        cmd = ["arecord", "-D", device_arg, "-f", "S16_LE", "-r", "16000", "-d", "5", "-q", str(out_path)]
        subprocess.run(cmd, check=False)
        return out_path
    
    except Exception as e:
        print(f"[record] Error: {e}")
        return out_path

# Alias
record_audio = record_until_silence

# --- Stubs ---
def load_pocketsphinx_decoder(*args, **kwargs): return False
def wait_for_wake_word(*args, **kwargs): return False
def stop_process(*args, **kwargs): pass
def set_volume(*args, **kwargs): pass
def quick_stt(*args, **kwargs): return ""
def synthesize_to_wav(*args, **kwargs): return None

