"""
Optimized Audio Utilities for Pi Zero W.
Restored Google STT and robust TTS.
"""
import os
import sys
import time
import subprocess
import threading
import shutil
import tempfile
try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
import math
import math
from typing import Optional
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
    WAKE_WORDS,
    LAST_AUDIO,
    BLUETOOTH_SPEAKER_MAC,
    MIC_DEVICE_INDEX,
    BLUETOOTH_HCI, # Added by user instruction
    PIPER_EXECUTABLE, # Added by user instruction
    PIPER_VOICE_MODEL, # Added by user instruction
    MUTE_MODE, # Added by user instruction
    MAX_RECORD_SECONDS,
    SILENCE_TIMEOUT,
    PHRASE_TIME_LIMIT,
    STT_ENGINE, 
    GEMINI_API_KEY, 
    GEMINI_API_KEY_BACKUP, 
    PORCUPINE_ACCESS_KEY,
    GROQ_API_KEY
)

# Hardcoded settings for PulseAudio
ALSA_DEVICE = "pulse" 
BUFFER_TIME = "250000" # Faster buffer (0.25s)

def _transcribe_with_groq(audio_data) -> str:
    """Fast transcription using Groq API (Whisper-v3)."""
    if not GROQ_API_KEY:
        return ""
    try:
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
        
        # Groq needs a file-like object with a proper extension
        files = {
            "file": ("audio.wav", audio_data.get_wav_data(), "audio/wav"),
            "model": (None, "whisper-large-v3"),
            "language": (None, "en"),
            "response_format": (None, "json")
        }
        
        resp = requests.post(url, headers=headers, files=files, timeout=5)
        if resp.ok:
            return resp.json().get("text", "")
    except Exception as e:
        print(f"[groq-stt] Error: {e}")
    return ""

def setup_microphone_volume():
    """Force hardware capture gain to 100% using amixer."""
    try:
        # Standard USB Mic / Pi Zero mic control names
        controls = ["Capture", "Mic", "Internal Mic", "Digital"]
        for control in controls:
            subprocess.run(["amixer", "sset", control, "100%"], capture_output=True)
        print("[audio] Hardware capture gain set to 100%.")
    except Exception as e:
        print(f"[audio] Failed to set hardware volume: {e}")


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
    Delegate text-to-speech rendering to the improved hybrid audio_utils_simple
    which handles chunking, fast caching, and drops espeak entirely.
    """
    from .audio_utils_simple import speak as simple_speak
    simple_speak(text)

def _apply_webrtc_vad(audio_data):
    """Filter out non-speech (noise) frames using WebRTC VAD."""
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return audio_data
    try:
        import webrtcvad
        vad = webrtcvad.Vad(3) # Aggressiveness 0-3 (3 is most aggressive)
        
        # WebRTC only supports 8000, 16000, 32000, or 48000 Hz, 16-bit
        supported_rates = [8000, 16000, 32000, 48000]
        if audio_data.sample_rate not in supported_rates or audio_data.sample_width != 2:
            return audio_data # Skip if incompatible
            
        raw_data = audio_data.get_raw_data()
        
        # 30 ms frames
        frame_duration_ms = 30
        frame_size = int(audio_data.sample_rate * (frame_duration_ms / 1000.0) * audio_data.sample_width)
        
        filtered_data = bytearray()
        for i in range(0, len(raw_data) - frame_size + 1, frame_size):
            frame = raw_data[i:i + frame_size]
            if vad.is_speech(frame, audio_data.sample_rate):
                filtered_data.extend(frame)
                
        # If VAD stripped everything (e.g., pure silence), return the original
        if len(filtered_data) < frame_size * 5: # At least 150ms of speech
            return audio_data
            
        return sr.AudioData(bytes(filtered_data), audio_data.sample_rate, audio_data.sample_width)
        
    except ImportError:
        print("[audio] webrtcvad not installed, skipping noise suppression.")
        return audio_data
    except Exception as e:
        print(f"[audio] VAD pass error: {e}")
        return audio_data

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

def _apply_speex_denoise(audio_data):
    """
    Native SpeexDSP noise suppression using OS binaries for Pi Zero efficiency.
    Requires 'speexdsp-tools' to be installed (`sudo apt install speexdsp-tools`).
    """
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return audio_data
    if not shutil.which("speexenc") or not shutil.which("speexdec"):
        return audio_data

    try:
        raw_path = tempfile.mktemp(suffix=".wav")
        spx_path = tempfile.mktemp(suffix=".spx")
        clean_path = tempfile.mktemp(suffix=".wav")

        with open(raw_path, "wb") as f:
            f.write(audio_data.get_wav_data())

        # Try with --denoise flag first; fall back to plain encode if unsupported
        try:
            subprocess.run(["speexenc", "--denoise", raw_path, spx_path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except subprocess.CalledProcessError:
            subprocess.run(["speexenc", raw_path, spx_path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        subprocess.run(["speexdec", spx_path, clean_path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        with sr.AudioFile(clean_path) as source:
            clean_audio = sr.Recognizer().record(source)

        for p in [raw_path, spx_path, clean_path]:
            if os.path.exists(p): os.remove(p)

        return clean_audio
    except Exception:
        # Speex denoising is optional — silently fall back to original audio
        return audio_data

import base64
import json
import requests
from .config import BACKEND_URL

def live_stt_listen(recognizer, mic, slug, timeout=7, phrase_time_limit=10):
    """
    Direct Google STT for maximum reliability.
    Uses SpeechRecognition's recognize_google method locally.
    """
    try:
        # Use existing context if source is already open, else open it
        if hasattr(mic, 'stream') and mic.stream is not None:
            print("[stt] Listening (active stream)...", flush=True)
            audio = recognizer.listen(mic, timeout=timeout, phrase_time_limit=phrase_time_limit)
        else:
            with mic as source:
                print("[stt] Listening...", flush=True)
                audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            
        # Apply normalization to improve recognition
        audio = _normalize_audio(audio)
        
        # 🚀 Use Groq if available (Whisper-v3 is ~5x faster than Google)
        if GROQ_API_KEY:
            print("[stt] Processing via Groq STT...", flush=True)
            text = _transcribe_with_groq(audio)
            if text:
                print(f"[stt] Heard (Groq): '{text}'", flush=True)
                return text

        print("[stt] Processing via Google STT...", flush=True)
        # Local Google Recognition (Bypasses backend errors)
        text = recognizer.recognize_google(audio)
        
        if text:
            print(f"[stt] Heard (Google): '{text}'", flush=True)
            return text
            
    except sr.UnknownValueError:
        # Noise or no speech detected
        pass
    except sr.RequestError as e:
        print(f"[stt] Google API Error: {e}", flush=True)
    except sr.WaitTimeoutError:
        pass
    except Exception as e:
        print(f"[stt] STT Error: {e}", flush=True)
        
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
            
            # 🚀 Prefer Groq (Instant response)
            if GROQ_API_KEY:
                print("[stt] Processing via Groq STT...", flush=True)
                return _transcribe_with_groq(audio)

            if STT_ENGINE == "gemini":
                try:
                    wav_data = audio.get_wav_data()
                    # transcribe_audio should be Defined as gemini_client.transcribe_audio
                    from .gemini_client import transcribe_audio
                    return transcribe_audio(wav_data, api_key=GEMINI_API_KEY or GEMINI_API_KEY_BACKUP)
                except Exception as e:
                    print(f"[stt] Gemini STT error: {e}")
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

def record_until_silence(out_path=LAST_AUDIO, silence_duration=None, recognizer=None, mic=None) -> Optional[Path]:
    """
    Record audio with VAD (Silence Detection) for 'Alexa-style' interaction.
    Uses speech_recognition's built-in energy thresholding.
    """
    # Use config default if none provided
    if silence_duration is None:
        silence_duration = SILENCE_TIMEOUT

    # Delete old file to prevent ghost repeats
    if os.path.exists(out_path):
        os.remove(out_path)

    if SPEECH_RECOGNITION_AVAILABLE and sr is not None:
        try:
            r = recognizer if recognizer else sr.Recognizer()
            # 🚀 Set pause threshold BEFORE starting to listen
            r.pause_threshold = silence_duration
            
            # Default thresholds (overridden by dynamic or calibration)
            if not recognizer:
                r.energy_threshold = 200 # More sensitive starting point
                r.dynamic_energy_threshold = True
                r.dynamic_energy_ratio = 1.5 # 🚀 Catch even soft tails of sentences
            
            # Use provided mic or create new one with ALSA suppression
            if mic:
                source_ctx = mic
            else:
                with no_alsa_err():
                    source_ctx = sr.Microphone(device_index=MIC_DEVICE_INDEX)
            
            # If we create new mic, we need context manager. If passed, it depends if it's open.
            is_open_source = isinstance(source_ctx, sr.AudioSource) and getattr(source_ctx, "stream", None) is not None

            print(f"[record] Listening... (Pause Threshold: {r.pause_threshold}s)")
            
            if is_open_source:
                # 🚀 Increased phrase limit so user doesn't get cut off
                audio = r.listen(source_ctx, timeout=8, phrase_time_limit=PHRASE_TIME_LIMIT)
            else:
                with source_ctx as source:
                    if not recognizer:
                         # Very brief calibration if it's a fresh recognizer
                         r.adjust_for_ambient_noise(source, duration=0.2)
                         r.energy_threshold = max(r.energy_threshold, 100) # Ensure it's not TOO low
                         
                    audio = r.listen(source, timeout=8, phrase_time_limit=PHRASE_TIME_LIMIT)
            
            # 🚀 Restored High-Fidelity Audio Pipeline
            # 1. Pre-Normalization (Boost quiet signals for cleaner denoising)
            boosted_audio = _normalize_audio(audio, target_level=30000)
            
            # 2. Apply WebRTC VAD to strip pure noise
            clean_audio = _apply_webrtc_vad(boosted_audio)
            
            # 3. Apply Speex Denoise (System noise remover)
            denoised_audio = _apply_speex_denoise(clean_audio)
            
            # 4. Final Normalization (Target level for Google STT)
            final_audio = _normalize_audio(denoised_audio, target_level=25000)
            
            with open(out_path, "wb") as f:
                f.write(final_audio.get_wav_data())
            
            return Path(out_path)
            
        except sr.WaitTimeoutError:
            print("[record] Timeout (silence)")
            return None
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
        return Path(out_path)
    except Exception as e:
        print(f"[record] Fallback Error: {e}")
        return None
    
    except Exception as e:
        print(f"[record] Error: {e}")
        return out_path

# Alias
record_audio = record_until_silence

import json
import wave

# Vosk Model Holder (DEPRECATED FOR ARMV6L POCKETSPHINX)
_vosk_model = None

def load_vosk_model() -> bool:
    """Legacy stub. Vosk has been replaced by PocketSphinx on ARMv6l architecture."""
    return False

def quick_stt(audio_path: str) -> str:
    """
    Perform offline STT using PocketSphinx.
    Reads the given wav file and returns the transcribed text.
    """
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return ""
    if not os.path.exists(audio_path):
        return ""
            
    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(str(audio_path)) as source:
            audio = recognizer.record(source)
            if _SPHINX_CUSTOM_KEYWORDS:
                text = recognizer.recognize_sphinx(audio, keyword_entries=_SPHINX_CUSTOM_KEYWORDS)
            else:
                text = recognizer.recognize_sphinx(audio)
            print(f"[sphinx] Offline Heard: '{text}'")
            return text
    except Exception as e:
        print(f"[sphinx] Offline STT Error: {e}")
        return ""

def wait_for_wake_word(use_offline: bool = True, recognizer=None, mic=None) -> bool:
    """
    Ultra-low CPU wake word detection using Picovoice Porcupine (offline default).
    If use_offline=False or unsupported architecture, falls back to standard live listening.
    Continuously listens for "porcupine" (or configured wake word) 
    and returns True when heard.
    """
    import platform
    is_arm = platform.machine() == "armv6l"
    
    if not PORCUPINE_ACCESS_KEY:
        if not is_arm:
            print("[porcupine] ❌ ERROR: PORCUPINE_ACCESS_KEY not found in .env files.")
            print("   Get one for free at console.picovoice.ai and add it to .env")
        use_offline = False
        
    if use_offline and not is_arm:
        try:
            import pvporcupine
            import pyaudio
            import struct
            
            # Initialize Porcupine with the default built-in "porcupine" keyword
            # To use "computer", "jarvis", etc., change keywords=["porcupine"]
            porcupine = pvporcupine.create(
                access_key=PORCUPINE_ACCESS_KEY,
                keywords=["porcupine"]
            )
            
            pa = pyaudio.PyAudio()
            
            print(f"\n[wake] 🦔 Porcupine Engine Started. Listening for wake word...")
            
            audio_stream = pa.open(
                rate=porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=porcupine.frame_length,
                input_device_index=MIC_DEVICE_INDEX
            )
            
            while True:
                pcm = audio_stream.read(porcupine.frame_length, exception_on_overflow=False)
                pcm = struct.unpack_from("h" * porcupine.frame_length, pcm)
                
                keyword_index = porcupine.process(pcm)
                
                if keyword_index >= 0:
                    print(f"\n[wake] 🦔 Wake Word Detected!")
                    audio_stream.stop_stream()
                    audio_stream.close()
                    pa.terminate()
                    porcupine.delete()
                    
                    # Play hardware beep to acknowledge
                    subprocess.run(
                        ["play", "-n", "-c1", "synth", "0.1", "sine", "800", "vol", "0.5"],
                        stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, check=False
                    )
                    return True
                    
        except ImportError:
            print("[wake] 🦔 Porcupine not installed (unsupported architecture). Falling back to Sphinx offline loop.")
            use_offline = True  # We stay offline, but use Sphinx fallback
            porcupine_failed = True
        except Exception as e:
            print(f"[wake] 🦔 Porcupine Error: {e}. Falling back to Sphinx offline loop.")
            use_offline = True
            porcupine_failed = True

    # Fallback / Online Loop
    fallback_active = ("porcupine_failed" in locals() and porcupine_failed) or not use_offline
    if fallback_active and SPEECH_RECOGNITION_AVAILABLE and sr is not None:
        if use_offline:
            print(f"\n[wake] 📡 Offline Sphinx Listening for '{WAKE_WORD}'...")
        else:
            print(f"\n[wake] ☁️  Standard Mic Listening for '{WAKE_WORD}'...")
            
        r = recognizer if recognizer else sr.Recognizer()
        if not recognizer:
            r.energy_threshold = 400
            r.dynamic_energy_threshold = True
        
        try:
            if mic:
                mic_source = mic
            else:
                with no_alsa_err():
                    mic_source = sr.Microphone(device_index=MIC_DEVICE_INDEX)
            
            # If we create new mic, we need context manager. If passed, it depends if it's open.
            is_open_source = isinstance(mic_source, sr.AudioSource) and getattr(mic_source, "stream", None) is not None

            def _listen_loop(source):
                while True:
                    try:
                        audio = r.listen(source, timeout=2, phrase_time_limit=3)
                        
                        # Routing transcribe engine
                        if use_offline:
                             if _SPHINX_CUSTOM_KEYWORDS:
                                 text = r.recognize_sphinx(audio, keyword_entries=_SPHINX_CUSTOM_KEYWORDS).lower()
                             else:
                                 text = r.recognize_sphinx(audio).lower()
                        else:
                             text = r.recognize_google(audio).lower()
                             
                        print(f"   (heard: '{text}')", end="\r")
                        if WAKE_WORD.lower() in text or any(w in text for w in WAKE_WORDS):
                            print("\n[wake] 🟢 Wake Word Detected!")
                            try:
                                subprocess.run(
                                    ["play", "-n", "-c1", "synth", "0.1", "sine", "800", "vol", "0.5"],
                                    stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, check=False
                                )
                            except FileNotFoundError:
                                print("\a", end="", flush=True)
                            return True
                    except sr.WaitTimeoutError:
                        continue
                    except sr.UnknownValueError:
                        continue
                    except Exception as loop_e:
                        print(f"   (Sphinx/Google engine skip: {loop_e})", end="\r")
                        continue

            if is_open_source:
                return _listen_loop(mic_source)
            else:
                with no_alsa_err():
                    with mic_source as source:
                        if not recognizer:
                            r.adjust_for_ambient_noise(source, duration=0.5)
                        return _listen_loop(source)

        except Exception as e:
            print(f"[wake] Mic Error: {e}")
            time.sleep(2)
            return False
            
    time.sleep(2)
    return False
def stop_process(*args, **kwargs): pass

def set_volume(change=0):
    """
    Adjust system volume.
    change: int — positive = up, negative = down.
    Values >= 50 treated as absolute % (e.g. startup set_volume(80) → 80%).
    """
    try:
        if change == 0 or not shutil.which("pactl"):
            return

        # Target BT sink by name so it works even if @DEFAULT_SINK@ is wrong
        bt_sink = f"bluez_output.{BLUETOOTH_SPEAKER_MAC.replace(':', '_')}.1"

        if abs(change) >= 50:
            # Absolute volume (startup call)
            vol_str = f"{abs(change)}%"
        else:
            # Relative change (+10% / -10%)
            vol_str = f"{'+' if change > 0 else '-'}{abs(change)}%"

        subprocess.run(["pactl", "set-sink-volume", bt_sink, vol_str],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", vol_str],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[audio] Volume → {vol_str}")
    except Exception as e:
        print(f"[audio] Error setting volume: {e}")

def synthesize_to_wav(*args, **kwargs): return None
