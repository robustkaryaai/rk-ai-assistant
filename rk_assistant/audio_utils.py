"""
Optimized Audio Utilities for Pi Zero W.
Restored Google STT and robust TTS.
Features: SmartSTTEngine (constant background listening), mute/unmute support, night protocol.
"""
import os
import sys
import time
import queue
import subprocess
import threading
import shutil
import tempfile
import requests

_stt_log_guard = threading.Lock()
_last_stt_log_times = {}

def _resolve_stt_slug() -> str:
    slug = os.getenv("DEVICE_SLUG")
    if slug:
        return str(slug).strip()
    try:
        from .networking import read_slug
        resolved, _ = read_slug()
        return str(resolved or "").strip()
    except Exception:
        return ""

def _push_stt_log(text: str, throttle_sec: float = 0.0):
    """Pushes transcribed text to the backend stream for the RK AI Home mobile app."""
    if not text or not text.strip(): return
    slug = _resolve_stt_slug()
    if not slug: return
    clean_text = str(text).strip()
    if throttle_sec > 0:
        now = time.time()
        key = clean_text.lower()
        with _stt_log_guard:
            last = _last_stt_log_times.get(key, 0.0)
            if (now - last) < throttle_sec:
                return
            _last_stt_log_times[key] = now
    try:
        url = f"https://rk-ai-backend.onrender.com/device/{slug}/stt-log"
        # Run asynchronously so we don't block the audio loop
        def _worker():
            try:
                requests.post(url, json={"text": clean_text}, timeout=2)
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True).start()
    except:
        pass


def log_stt_status(text: str, throttle_sec: float = 0.0):
    """Public helper for status-style STT log messages."""
    _push_stt_log(text, throttle_sec=throttle_sec)

try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop
import math
from typing import Optional, Callable
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
    BLUETOOTH_HCI,
    PIPER_EXECUTABLE,
    PIPER_VOICE_MODEL,
    MUTE_MODE,
    MAX_RECORD_SECONDS,
    SILENCE_TIMEOUT,
    PHRASE_TIME_LIMIT,
    STT_ENGINE,
    STT_ENGINE_ONLINE,
    GEMINI_API_KEY,
    GEMINI_API_KEY_BACKUP,
    PORCUPINE_ACCESS_KEY,
    GROQ_API_KEY,
    NIGHT_AMBIENT_THRESHOLD,
    NIGHT_CHECK_INTERVAL,
    NIGHT_CONFIRM_COUNT,
    NIGHT_PAUSE_THRESHOLD,
    NIGHT_ENERGY_BOOST,
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


def _transcribe_with_google(audio_data) -> str:
    """Transcribe audio with Google Speech Recognition and one normalized retry."""
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return ""

    recognizer = sr.Recognizer()
    try:
        text = recognizer.recognize_google(audio_data)
        if text:
            return text
    except sr.UnknownValueError:
        pass
    except sr.RequestError as e:
        print(f"[stt] Google API Error: {e}", flush=True)
        return ""

    try:
        norm_audio = _normalize_audio(audio_data)
        text = recognizer.recognize_google(norm_audio)
        if text:
            print(f"[stt] (Normalized) Heard: '{text}'", flush=True)
            return text
    except Exception as e:
        print(f"[stt] Google retry error: {e}", flush=True)

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
    Delegate text-to-speech rendering to the lightweight Flite-first hybrid
    wrapper used across the assistant.
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

def online_stt(audio_path: Path, prefer_google: bool = False) -> str:
    """Transcribe audio file using Google STT."""
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return ""
    if not os.path.exists(audio_path):
        return ""
        
    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(str(audio_path)) as source:
            audio = recognizer.record(source)

            if prefer_google or STT_ENGINE_ONLINE == "google":
                return _transcribe_with_google(audio)

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

            return _transcribe_with_google(audio)
                
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
                             
                        print(f"[stt] (heard: '{text}')", flush=True)
                        _push_stt_log(text)
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


def ensure_bluetooth_audio_route() -> str:
    """
    Best-effort route audio to the configured Bluetooth speaker sink.
    Returns the sink name we selected, or an empty string if we could not find one.
    """
    if not shutil.which("pactl"):
        return ""

    try:
        bt_mac = BLUETOOTH_SPEAKER_MAC.replace(":", "_")
        preferred = f"bluez_output.{bt_mac}.1"

        sinks = subprocess.check_output(["pactl", "list", "short", "sinks"], text=True).splitlines()
        sink_names = []
        for line in sinks:
            parts = line.split("\t")
            if len(parts) >= 2:
                sink_names.append(parts[1].strip())

        selected = ""
        for sink in sink_names:
            if preferred in sink or "bluez_output" in sink:
                selected = sink
                break
        if not selected and sink_names:
            selected = sink_names[0]

        if selected:
            subprocess.run(["pactl", "set-default-sink", selected], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return selected
    except Exception as e:
        print(f"[audio] Could not select Bluetooth sink: {e}")
    return ""

def synthesize_to_wav(*args, **kwargs): return None


# ─────────────────────────────────────────────────────────────────────────────
# SmartSTTEngine — Constant background listener with night protocol support
# ─────────────────────────────────────────────────────────────────────────────

_SPHINX_CUSTOM_KEYWORDS_STR = [(w, 1e-10) for w in WAKE_WORDS]
# Alias used by legacy quick_stt / wait_for_wake_word functions
_SPHINX_CUSTOM_KEYWORDS = _SPHINX_CUSTOM_KEYWORDS_STR


class SmartSTTEngine:
    """
    Always-on STT engine that runs a `listen_in_background()` loop.

    Features:
    • Constant listening — zero startup delay.
    • Online: Google STT (or Groq if GROQ_API_KEY set).
    • Offline: PocketSphinx with wake-word filter.
    • Mute: listener thread is fully stopped; restarted on unmute.
    • Night mode: higher energy threshold + longer pause → less false triggers;
                  TTS suppression flag is set (honoured by main.py).
    • Commands land in `command_queue` — main loop just does .get().
    """

    def __init__(
        self,
        recognizer,
        mic,
        online: bool = True,
        on_wake: Optional[Callable] = None,
    ):
        """
        Parameters
        ----------
        recognizer  : sr.Recognizer (already calibrated)
        mic         : sr.Microphone
        online      : initial online state
        on_wake     : optional callback(text) called on every matched command
                      (in addition to queuing)
        """
        self.recognizer = recognizer
        self.mic = mic
        self.online = online
        self.on_wake = on_wake

        # Thread-safe queue; main loop reads from here
        self.command_queue: queue.Queue[str] = queue.Queue()

        # Internal state
        self._stop_listening = None   # The callable returned by listen_in_background
        self._running = False
        self._night_mode = False
        self._base_energy = recognizer.energy_threshold if recognizer else 300
        self._lock = threading.Lock()

    # ── public API ────────────────────────────────────────────────────────────

    def start(self):
        """Start the background listener."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._launch_listener()
            print("[stt-engine] 🎙️  SmartSTTEngine started.", flush=True)

    def stop(self):
        """Stop the background listener immediately."""
        with self._lock:
            self._running = False
            if self._stop_listening:
                try:
                    self._stop_listening(wait_for_stop=True)
                except Exception:
                    pass
                self._stop_listening = None
            print("[stt-engine] ⏹️  SmartSTTEngine stopped.", flush=True)

    def restart(self):
        """Stop then start (used after unmute or recalibration)."""
        self.stop()
        time.sleep(0.4)
        with self._lock:
            self._running = True
            self._launch_listener()
        print("[stt-engine] 🔄  SmartSTTEngine restarted.", flush=True)

    def set_online(self, online: bool):
        """Update online/offline state; restarts listener to apply."""
        if self.online != online:
            self.online = online
            self.restart()

    def set_night_mode(self, enabled: bool):
        """Apply / remove night protocol tuning and restart listener."""
        if self._night_mode == enabled:
            return
        self._night_mode = enabled
        self._apply_night_tuning()
        self.restart()
        if enabled:
            print("[stt-engine] 🌙  Night mode ON — STT slowed, TTS suppression active.")
        else:
            print("[stt-engine] ☀️   Night mode OFF — normal STT restored.")

    @property
    def night_mode(self) -> bool:
        return self._night_mode

    # ── internal helpers ──────────────────────────────────────────────────────

    def _apply_night_tuning(self):
        r = self.recognizer
        if r is None:
            return
        if self._night_mode:
            r.pause_threshold = NIGHT_PAUSE_THRESHOLD
            r.energy_threshold = self._base_energy * NIGHT_ENERGY_BOOST
            r.dynamic_energy_threshold = False   # Keep fixed threshold at night
        else:
            r.pause_threshold = 1.2
            r.energy_threshold = self._base_energy
            r.dynamic_energy_threshold = True

    def _launch_listener(self):
        """Start listen_in_background — must be called inside _lock."""
        if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
            print("[stt-engine] ⚠️  speech_recognition unavailable — engine idle.")
            return
        try:
            self._stop_listening = self.recognizer.listen_in_background(
                self.mic,
                self._on_audio,
                phrase_time_limit=PHRASE_TIME_LIMIT,
            )
        except Exception as e:
            print(f"[stt-engine] Failed to start background listener: {e}")
            self._running = False

    def _on_audio(self, recognizer, audio):
        """
        Called by speech_recognition's background thread every time a phrase
        is captured.  We run STT here and push matching commands to the queue.
        """
        if not self._running:
            return
        try:
            text = self._transcribe(recognizer, audio)
        except Exception as e:
            print(f"[stt-engine] Transcription error: {e}")
            log_stt_status("Couldn't understand that.", throttle_sec=4.0)
            return

        if not text:
            log_stt_status("Couldn't understand that.", throttle_sec=4.0)
            return

        text_lower = text.lower().strip()
        print(f"[stt-engine] Heard: '{text_lower}'", flush=True)
        _push_stt_log(text_lower)

        # Check for wake word
        wake_detected = (
            WAKE_WORD.lower() in text_lower
            or any(w in text_lower for w in WAKE_WORDS)
        )

        if wake_detected:
            # Strip the wake word prefix to get the actual command
            command = self._strip_wake_word(text_lower)
            print(f"[stt-engine] 🟢 Wake word! Command: '{command}'", flush=True)
            self.command_queue.put(command or "__WAKE__")
            if self.on_wake:
                try:
                    self.on_wake(command or "__WAKE__")
                except Exception:
                    pass

    def _transcribe(self, recognizer, audio) -> str:
        """Run the appropriate STT engine and return text."""
        # Boost audio first
        audio = _normalize_audio(audio)

        if self.online:
            # Priority: Groq → Google
            if GROQ_API_KEY and STT_ENGINE_ONLINE != "google":
                text = _transcribe_with_groq(audio)
                if text:
                    return text
            try:
                return recognizer.recognize_google(audio)
            except sr.UnknownValueError:
                return ""
            except sr.RequestError as e:
                print(f"[stt-engine] Google API error: {e} — falling back to offline", flush=True)
                # fall through to offline
        # Offline: PocketSphinx
        try:
            return recognizer.recognize_sphinx(audio)
        except Exception:
            return ""

    @staticmethod
    def _strip_wake_word(text: str) -> str:
        """Remove the leading wake word from a transcribed string."""
        # Check all wake words (longest first to avoid partial matches)
        for ww in sorted(WAKE_WORDS, key=len, reverse=True):
            idx = text.find(ww)
            if idx != -1:
                return text[idx + len(ww):].strip(" ,.").strip()
        return text.strip()


def create_stt_engine(
    recognizer,
    mic,
    online: bool = True,
    on_wake: Optional[Callable] = None,
) -> SmartSTTEngine:
    """
    Factory: create and configure a SmartSTTEngine.
    Does NOT call .start() — caller must do that.
    """
    engine = SmartSTTEngine(recognizer, mic, online=online, on_wake=on_wake)
    return engine


def measure_ambient_rms(mic, recognizer, duration: float = 1.5) -> float:
    """
    Capture a short audio snippet and return its RMS level.
    Used by the night-protocol checker in main.py.
    Returns 0.0 on failure.
    """
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None or mic is None:
        return 0.0
    try:
        with no_alsa_err():
            with mic as source:
                # Listen briefly
                audio = recognizer.record(source, duration=duration)
        raw = audio.get_raw_data()
        if not raw:
            return 10.0 # Return small baseline instead of 0
        rms = audioop.rms(raw, 2)
        return float(rms)
    except Exception as e:
        # If resource is busy, return a 'loud enough' value to prevent entering night mode by mistake
        if "busy" in str(e).lower() or "resource" in str(e).lower():
            return float(NIGHT_AMBIENT_THRESHOLD + 1)
        print(f"[audio] RMS error: {e}")
        return 10.0
