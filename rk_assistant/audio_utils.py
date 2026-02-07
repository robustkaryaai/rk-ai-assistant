"""
Optimized Audio Utilities for Pi Zero W.
Focus: Low CPU overhead, direct ALSA access, no complex logic.
"""
import os
import sys
import time
import subprocess
import threading
from pathlib import Path

# Configuration
from .config import (
    SAMPLE_RATE, 
    CHANNELS, 
    POCKETSPHINX_MODEL_DIR,
    WAKE_WORD,
    LAST_AUDIO,
    BLUETOOTH_SPEAKER_MAC
)

# Hardcoded optimal settings for Pi Zero W
ALSA_DEVICE = f"bluealsa:DEV={BLUETOOTH_SPEAKER_MAC},PROFILE=a2dp"
BUFFER_TIME = "500000" # 0.5s buffer (balance latency/stability)

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

# --- STT Stubs (Keep unrelated logic minimum) ---
def wait_for_wake_word(*args, **kwargs): return False
def live_stt_listen(*args, **kwargs): return ""
def record_audio(*args, **kwargs): return None
