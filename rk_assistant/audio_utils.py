"""
Unified Audio Utilities for RK AI.
Combines:
1. Simple, robust TTS (Piper/gTTS/espeak) from audio_utils_simple.
2. Listening logic (PocketSphinx/GoogleSTT) from old_files/audio_utils_past.
"""
from __future__ import annotations

import os
import sys
import time
import subprocess
import threading
import hashlib
from pathlib import Path
from typing import Optional, List, Union

import sounddevice as sd  # type: ignore

# Configuration
from .config import (
    SAMPLE_RATE, 
    CHANNELS, 
    POCKETSPHINX_MODEL_DIR,
    WAKE_WORD,
    LAST_AUDIO,
    MAX_RECORD_SECONDS
)

# --- 1. TTS MODULE (Imported from audio_utils_simple logic) ---
from .audio_utils_simple import speak, is_online, _speak_with_piper, _is_piper_available

# --- 2. DEPENDENCY CHECKS ---
try:
    from pocketsphinx import LiveSpeech
    POCKETSPHINX_AVAILABLE = True
except Exception:
    LiveSpeech = None
    POCKETSPHINX_AVAILABLE = False

try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_AVAILABLE = True
except Exception:
    sr = None
    SPEECH_RECOGNITION_AVAILABLE = False

if SPEECH_RECOGNITION_AVAILABLE:
    # Reduce verbose logging from SR
    pass


# --- 3. LISTENING FUNCTIONS ---

def load_pocketsphinx_decoder() -> bool:
    """Check if PocketSphinx is available and ready."""
    if not POCKETSPHINX_AVAILABLE or LiveSpeech is None:
        return False
    try:
        # Test initialization
        test = LiveSpeech(verbose=False, no_search=True)
        del test
        return True
    except Exception as e:
        print(f"[audio] PocketSphinx init failed: {e}")
        return False

def wait_for_wake_word(decoder_available: bool, wake_word: Union[str, List[str]] = WAKE_WORD, max_seconds: float = None) -> bool:
    """
    Listen for wake word using PocketSphinx (Offline).
    Blocks until heard or timeout.
    """
    if not decoder_available or LiveSpeech is None:
        print("[wake] Decoder unavailable, sleeping 5s...")
        time.sleep(5)
        return False

    wake_words = [wake_word] if isinstance(wake_word, str) else wake_word
    wake_words = [w.lower() for w in wake_words]
    
    config = {
        'verbose': False,
        'sampling_rate': 16000,
        'buffer_size': 2048,
        'no_search': False,
        'full_utt': False
    }
    
    # Optimization for single word
    if len(wake_words) == 1:
        config['keyphrase'] = wake_words[0]
        config['kws_threshold'] = 1e-20

    # Model paths
    model_path = POCKETSPHINX_MODEL_DIR
    if model_path and Path(model_path).exists():
        config['hmm'] = str(Path(model_path) / 'acoustic-model')
        config['dict'] = str(Path(model_path) / 'pronunciation-dictionary.dict')

    try:
        speech = LiveSpeech(**config)
        start = time.time()
        
        for phrase in speech:
            if max_seconds and (time.time() - start) > max_seconds:
                return False
                
            text = str(phrase).strip().lower()
            if any(w in text for w in wake_words):
                return True
            
            # Reset timeout safety
            if time.time() - start > 300:
                start = time.time()
                
    except Exception as e:
        print(f"[wake] Error: {e}")
        return False
        
    return False

def live_stt_listen(recognizer, mic, timeout=None, phrase_time_limit=None) -> str:
    """
    Listen and transcribe using Google STT (Online).
    Used in the main loop for continuous listening.
    """
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return ""
    
    try:
        with mic as source:
            # Short calibration
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
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
        # Prevent log spam on hardware failures
        print(f"[stt] Live listen error: {e}")
        time.sleep(1.0) 
        return ""


# --- 4. RECORDING / UTILS ---

def record_until_silence(out_path: Path, silence_duration: float = 2.0) -> Path:
    """Record audio until silence (simple wrapper using SR or SD)."""
    # For simplicity, we'll use a fixed duration backup or sounddevice if available.
    # Re-implementing the SD logic from past for robustness.
    try:
        import numpy as np
        duration = 10 # Cap
        sample_rate = 16000
        recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype='int16')
        sd.wait()
        
        import wave
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(recording.tobytes())
        return out_path
    except Exception as e:
        print(f"[record] Failed: {e}")
        return out_path

def record_audio(out_path: Path = LAST_AUDIO, seconds: int = 5) -> Path:
    return record_until_silence(out_path) # Fallback alias

def play_audio_url(url: str):
    """Play URL using mpg123."""
    if not url: return None
    try:
        return subprocess.Popen(["mpg123", "-q", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        return None

def stop_process(proc):
    if proc:
        proc.terminate()

def set_volume(delta: int):
    # From audio_utils_simple/past
    sign = "+" if delta >= 0 else ""
    subprocess.run(["amixer", "set", "PCM", f"{sign}{delta}%"], capture_output=True)

def quick_stt(decoder_available, seconds=3.0) -> str:
    """Quick offline STT check."""
    return "" # Stub for now

def online_stt(audio_path: Path) -> str:
    """Transcribe audio file online."""
    if not SPEECH_RECOGNITION_AVAILABLE: return ""
    r = sr.Recognizer()
    try:
        with sr.AudioFile(str(audio_path)) as source:
            audio = r.record(source)
        return r.recognize_google(audio)
    except:
        return ""

def synthesize_to_wav(text: str, out_path: Path):
    """Synthesize speech to WAV (espeak)."""
    subprocess.run(["espeak", "-w", str(out_path), text], stderr=subprocess.DEVNULL)
