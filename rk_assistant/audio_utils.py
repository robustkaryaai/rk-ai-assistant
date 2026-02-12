"""
Optimized Audio Utilities for Pi Zero W.
Restored Google STT and robust TTS.
"""
import os
import sys
import time
import subprocess
import threading
try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
import math
import math
from pathlib import Path
from ctypes import *
from contextlib import contextmanager

# ALSA Error Handler suppression (CTYPES)
try:
    ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
    def py_error_handler(filename, line, function, err, fmt):
        pass
    c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
except:
    pass

@contextmanager
def no_alsa_err():
    try:
        asound = cdll.LoadLibrary('libasound.so')
        asound.snd_lib_error_set_handler(c_error_handler)
        yield
        asound.snd_lib_error_set_handler(None)
    except:
        yield

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
    MIC_DEVICE_INDEX,
    BLUETOOTH_HCI, # Added by user instruction
    PIPER_EXECUTABLE, # Added by user instruction
    PIPER_VOICE_MODEL, # Added by user instruction
    MUTE_MODE, # Added by user instruction
    STT_ENGINE, # Added by user instruction
    GEMINI_API_KEY, # Added by user instruction
    GEMINI_API_KEY_BACKUP # Added by user instruction
)

# Hardcoded settings for PulseAudio
ALSA_DEVICE = "pulse" 
BUFFER_TIME = "500000" # 0.5s buffer

def play_audio_file(file_path: str):
    """Ultra-smooth WAV playback using ffplay (Bluetooth-safe)."""
    if not os.path.exists(file_path):
        return

    try:
        subprocess.run(
            [
                "ffplay",
                "-nodisp",          # no window
                "-autoexit",        # exit after playback
                "-loglevel", "quiet",
                file_path
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"[audio] Play error: {e}")


def play_audio_url(url: str):
    """Play MP3 URL cleanly via PulseAudio (Bluetooth-safe)."""
    if not url:
        return None

    try:
        return subprocess.Popen(
            [
                "mpg123",

                # Force stable PulseAudio output
                "-o", "pulse",

                # BIG buffer = removes tick sound
                "-b", "8192",

                # Disable internal resync glitches
                "--no-resync",

                # Quiet mode
                "-q",

                url
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        return None


import re

def sanitize_text(text):
    """Remove emojis and non-standard symbols but keep basic punctuation and alphanumeric chars."""
    if not text: return ""
    # Keep alphanumeric (including unicode for Hindi etc), spaces, and basic punctuation
    # This regex removes most emojis/symbols
    return re.sub(r'[^\w\s,!.?\'"-]', '', text)

def speak(text):
    """
    Ultra-lightweight TTS via PulseAudio.
    """
    # Sanitize text (remove emojis)
    clean_text = sanitize_text(text)
    print(f"🔊 {text}") # Log original text with emoji for debugging
    
    # 1. Try Google TTS (Online) if enabled
    from .networking import is_online
    from .config import GTTS_ENABLE, GTTS_LANG, GTTS_TLD
    
    if GTTS_ENABLE and is_online():
        try:
            from gtts import gTTS
            tts = gTTS(text=clean_text, lang=GTTS_LANG, tld=GTTS_TLD)
            tts.save("/tmp/tts.mp3")
            proc = play_audio_url("/tmp/tts.mp3")
            if proc:
                proc.wait() # BLOCK until finished
            return
        except Exception as e:
            print(f"[tts] GTTS failed, falling back: {e}")

    try:
        # 2. Try Piper (Offline High Quality)
        piper_binary = "/usr/local/bin/piper"
        model = os.path.expanduser("~/.local/share/piper/voices/en_US-lessac-medium.onnx")
        
        if os.path.exists(piper_binary) and os.path.exists(model):
            # Pipe to aplay -D pulse
            # Escape quotes for shell
            safe_text = clean_text.replace('"', '\\"')
            cmd = f'echo "{safe_text}" | {piper_binary} --model {model} --output_raw | aplay -D {ALSA_DEVICE} -r 22050 -f S16_LE -t raw -q'
            subprocess.run(cmd, shell=True) # subprocess.run IS blocking by default
            return

        # 3. Fallback to espeak
        subprocess.run(
            ["espeak", "-w", "/tmp/tts.wav", clean_text], 
            check=False, stderr=subprocess.DEVNULL
        )
        play_audio_file("/tmp/tts.wav") # aplay is blocking
        
    except Exception as e:
        print(f"[tts] Error: {e}")

def _normalize_audio(audio_data, target_level=25000):
    """Normalize audio to target peak level (max 32767)."""
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return audio_data
    try:
        raw_data = audio_data.get_raw_data()
        max_val = audioop.max(raw_data, 2)
        
        if max_val == 0:
            return audio_data
            
        factor = target_level / max_val
        # Allow up to 15x boost for very quiet mics
        factor = min(factor, 15.0) 
        
        if factor > 1.05: # Only boost if significant
            boosted_raw = audioop.mul(raw_data, 2, factor)
            return sr.AudioData(boosted_raw, audio_data.sample_rate, audio_data.sample_width)
            
    except Exception as e:
        print(f"[audio] Normalization error: {e}")
        
    return audio_data

def live_stt_listen(recognizer, mic, timeout=None, phrase_time_limit=None) -> str:
    """
    Restore Google STT (Online).
    Accepts either a Microphone instance (opens/closes it) or an already open AudioSource.
    """
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return ""
    
    try:
        # Check if mic is actually a source (already open)
        is_open_source = False
        if isinstance(mic, sr.AudioSource) and hasattr(mic, "stream") and mic.stream is not None:
             is_open_source = True
             
        if is_open_source:
            source = mic
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        else:
            with mic as source:
                audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        
        if STT_ENGINE == "gemini":
            try:
                wav_data = audio.get_wav_data()
                text = transcribe_audio(wav_data, api_key=GEMINI_API_KEY or GEMINI_API_KEY_BACKUP)
                if text:
                    print(f"[stt] Gemini heard: '{text}'", flush=True)
                    return text
                else:
                    return ""
            except Exception as e:
                print(f"[stt] Gemini Error: {e}")
                return ""
        
        # Transcribe (Google Fallback)
        try:
            return recognizer.recognize_google(audio)
        except sr.UnknownValueError:
            # RETRY ONCE WITH NORMALIZATION
            try:
                norm_audio = _normalize_audio(audio)
                text = recognizer.recognize_google(norm_audio)
                print(f"[stt] (Normalized) Heard: '{text}'", flush=True)
                return text
            except Exception:
                print("[stt] Speech detected but unintelligible (even after norm).", flush=True)
                return ""
                
        except sr.RequestError as e:
            print(f"[stt] Google STT API Error: {e}", flush=True)
            return ""
            
    except sr.WaitTimeoutError:
        return "" 
    except Exception as e:
        print(f"[stt] Live listen error: {e}", flush=True)
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
            if STT_ENGINE == "gemini":
                try:
                    wav_data = audio.get_wav_data()
                    return transcribe_audio(wav_data, api_key=GEMINI_API_KEY or GEMINI_API_KEY_BACKUP)
                except:
                   return ""

            try:
                return recognizer.recognize_google(audio)
            except sr.UnknownValueError:
                # RETRY ONCE WITH NORMALIZATION
                try:
                    norm_audio = _normalize_audio(audio)
                    text = recognizer.recognize_google(norm_audio)
                    print(f"[stt] (Normalized) Heard: '{text}'", flush=True)
                    return text
                except Exception:
                    return ""
                
    except Exception:
        return ""

def record_until_silence(out_path=LAST_AUDIO, silence_duration=1.0) -> Path:
    """
    Record audio with VAD (Silence Detection) for 'Alexa-style' interaction.
    Uses speech_recognition's built-in energy thresholding.
    """
    if SPEECH_RECOGNITION_AVAILABLE and sr is not None:
        try:
            r = sr.Recognizer()
            r.pause_threshold = silence_duration
            r.energy_threshold = 300 
            r.dynamic_energy_threshold = True
            
            device_index = MIC_DEVICE_INDEX
            
            print(f"[record] Listening... (VAD enabled, silence={silence_duration}s)")
            with sr.Microphone(device_index=device_index) as source:
                # Fast calibration (optional, adds 0.5s latency but improves reliability)
                print("[record] Calibrating for 1s...", flush=True)
                r.adjust_for_ambient_noise(source, duration=1.0)
                
                # Listen automatically stops when silence is detected
                # phrase_time_limit ensures we don't record forever if noisy
                audio = r.listen(source, timeout=10, phrase_time_limit=15)
            
            # Save to WAV (Normalized)
            norm_audio = _normalize_audio(audio)
            with open(out_path, "wb") as f:
                f.write(norm_audio.get_wav_data())
            
            return out_path
            
        except sr.WaitTimeoutError:
            print("[record] Timeout (silence)")
            return out_path
        except Exception as e:
            print(f"[record] VAD Error: {e}")
            pass

    # Fallback to fixed duration arecord
    try:
        device_arg = "default"
        if MIC_DEVICE_INDEX is not None and MIC_DEVICE_INDEX >= 0:
            device_arg = f"plughw:{MIC_DEVICE_INDEX},0"
        
        print("[record] Fallback: Recording 5s fixed...")
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
def set_volume(change=0):
    """
    Adjust system volume.
    change: int (positive for up, negative for down).
    """
    try:
        # Use pactl (PulseAudio) first as we use -o pulse for mpg123
        if shutil.which("pactl"):
            # Format: +10% or -10%
            sign = "+" if change >= 0 else "-"
            # Ensure at least 5% change to be noticeable, but handle 0
            if change == 0: return
            
            # Limit volume max to 150%? pactl allows >100%.
            # Using relative change
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{abs(change)}%"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        elif shutil.which("amixer"):
            # Fallback to ALSA
            sign = "+" if change >= 0 else "-"
            subprocess.run(
                ["amixer", "sset", "Master", f"{abs(change)}%{sign}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        else:
             print("[audio] No volume control tool found (pactl/amixer).")
    except Exception as e:
        print(f"[audio] Error setting volume: {e}")
def quick_stt(*args, **kwargs): return ""
def synthesize_to_wav(*args, **kwargs): return None
