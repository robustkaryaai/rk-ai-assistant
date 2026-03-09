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
    LAST_AUDIO,
    BLUETOOTH_SPEAKER_MAC,
    MIC_DEVICE_INDEX,
    BLUETOOTH_HCI, # Added by user instruction
    PIPER_EXECUTABLE, # Added by user instruction
    PIPER_VOICE_MODEL, # Added by user instruction
    MUTE_MODE, # Added by user instruction
    STT_ENGINE, # Added by user instruction
    GEMINI_API_KEY, # Added by user instruction
    GEMINI_API_KEY_BACKUP, # Added by user instruction
    PORCUPINE_ACCESS_KEY
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
                clean_audio = _apply_webrtc_vad(audio)
                norm_audio = _normalize_audio(clean_audio)
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

def record_until_silence(out_path=LAST_AUDIO, silence_duration=1.0, recognizer=None, mic=None) -> Optional[Path]:
    """
    Record audio with VAD (Silence Detection) for 'Alexa-style' interaction.
    Uses speech_recognition's built-in energy thresholding.
    Pass pre-calibrated recognizer/mic to avoid latency.
    """
    # Delete old file to prevent ghost repeats
    if os.path.exists(out_path):
        os.remove(out_path)

    if SPEECH_RECOGNITION_AVAILABLE and sr is not None:
        try:
            r = recognizer if recognizer else sr.Recognizer()
            if not recognizer:
                r.pause_threshold = silence_duration
                r.energy_threshold = 300 
                r.dynamic_energy_threshold = True
            
            # Use provided mic or create new one
            source_ctx = mic if mic else sr.Microphone(device_index=MIC_DEVICE_INDEX)
            
            # If we create new mic, we need context manager. If passed, it depends if it's open.
            # Simplify: Always use context manager unless it's an AudioSource
            is_open_source = isinstance(source_ctx, sr.AudioSource) and getattr(source_ctx, "stream", None) is not None

            print(f"[record] Listening... (VAD enabled)")
            
            if is_open_source:
                audio = r.listen(source_ctx, timeout=5, phrase_time_limit=10)
            else:
                with source_ctx as source:
                    if not recognizer:
                         # Calibrate briefly but then force a LOW threshold
                         # so the user's voice is always detected
                         r.adjust_for_ambient_noise(source, duration=0.3)
                         # Cap threshold — calibration can set it too high in noisy rooms
                         r.energy_threshold = min(r.energy_threshold, 200)
                         r.dynamic_energy_threshold = False  # Lock it, don't drift up
                    audio = r.listen(source, timeout=8, phrase_time_limit=12)
            
            # Apply WebRTC VAD to strip pure noise
            clean_audio = _apply_webrtc_vad(audio)
            
            # Save to WAV (Normalized)
            norm_audio = _normalize_audio(clean_audio)
            with open(out_path, "wb") as f:
                f.write(norm_audio.get_wav_data())
            
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

# Vosk Model Holder
_vosk_model = None

def load_vosk_model() -> bool:
    """Load the Vosk offline model into memory."""
    global _vosk_model
    if _vosk_model is not None:
        return True
    
    try:
        from vosk import Model
        model_path = os.path.join(str(Path(__file__).parent), "model", "vosk-model")
        if not os.path.exists(model_path):
            print(f"[vosk] Model not found at {model_path}. Offline STT unavailable.")
            return False
            
        print("[vosk] Loading Vosk offline STT model...")
        _vosk_model = Model(model_path)
        print("[vosk] Model loaded successfully.")
        return True
    except Exception as e:
        print(f"[vosk] Error loading model: {e}")
        return False

def quick_stt(audio_path: str) -> str:
    """
    Perform offline STT using the loaded Vosk model.
    Reads the given wav file and returns the transcribed text.
    """
    global _vosk_model
    if not _vosk_model:
        if not load_vosk_model():
            return ""
            
    if not os.path.exists(audio_path):
        return ""
        
    try:
        from vosk import KaldiRecognizer
        
        wf = wave.open(audio_path, "rb")
        # Vosk expects mono PCM (which sr.AudioData.get_wav_data provides if mic is mono)
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
            print("[vosk] Audio file must be WAV format mono PCM.")
            wf.close()
            return ""
            
        rec = KaldiRecognizer(_vosk_model, wf.getframerate())
        rec.SetWords(False)
        
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            rec.AcceptWaveform(data)
            
        result_json = rec.FinalResult()
        wf.close()
        
        res = json.loads(result_json)
        text = res.get("text", "")
        if text:
             print(f"[vosk] Offline Heard: '{text}'")
        return text
        
    except Exception as e:
        print(f"[vosk] Offline STT error: {e}")
        return ""

def wait_for_wake_word(use_offline: bool = True) -> bool:
    """
    Ultra-low CPU wake word detection using Picovoice Porcupine (offline default).
    If use_offline=False or unsupported architecture, falls back to standard live listening.
    Continuously listens for "porcupine" (or configured wake word) 
    and returns True when heard.
    """
    if not PORCUPINE_ACCESS_KEY:
        print("[porcupine] ❌ ERROR: PORCUPINE_ACCESS_KEY not found in .env files.")
        print("   Get one for free at console.picovoice.ai and add it to .env")
        use_offline = False
        
    if use_offline:
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
            print("[wake] 🦔 Porcupine not installed (unsupported architecture). Falling back to online loop.")
            use_offline = False
        except Exception as e:
            print(f"[wake] 🦔 Porcupine Error: {e}. Falling back to online loop.")
            use_offline = False

    # Fallback / Online Loop
    if not use_offline and SPEECH_RECOGNITION_AVAILABLE and sr is not None:
        print(f"\n[wake] ☁️  Standard Mic Listening for '{WAKE_WORD}'...")
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 400
        recognizer.dynamic_energy_threshold = True
        
        try:
            with sr.Microphone(device_index=MIC_DEVICE_INDEX) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                while True:
                    try:
                        audio = recognizer.listen(source, timeout=2, phrase_time_limit=3)
                        text = recognizer.recognize_google(audio).lower()
                        print(f"   (heard: '{text}')", end="\r")
                        if WAKE_WORD.lower() in text or any(w in text for w in WAKE_WORDS):
                            print("\n[wake] 🟢 Wake Word Detected!")
                            subprocess.run(
                                ["play", "-n", "-c1", "synth", "0.1", "sine", "800", "vol", "0.5"],
                                stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL, check=False
                            )
                            return True
                    except sr.WaitTimeoutError:
                        continue
                    except sr.UnknownValueError:
                        continue
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
