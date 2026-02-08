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

# Hardcoded settings for PulseAudio
ALSA_DEVICE = "pulse" 
BUFFER_TIME = "500000" # 0.5s buffer

def play_audio_file(file_path: str):
    """Play WAV file using aplay via PulseAudio."""
    if not os.path.exists(file_path): return
    try:
        subprocess.run(
            ["aplay", "-D", ALSA_DEVICE, "-q", file_path],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"[audio] Play error: {e}")

def play_audio_url(url: str):
    """Play MP3 URL using mpg123 via PulseAudio."""
    if not url: return None
    try:
        # -o pulse specifies PulseAudio output
        return subprocess.Popen(
            ["mpg123", "-o", "pulse", "-b", "1024", "-q", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except:
        return None

def speak(text):
    """
    Ultra-lightweight TTS via PulseAudio.
    """
    print(f"🔊 {text}")
    
    # 1. Try Google TTS (Online) if enabled
    from .networking import is_online
    from .config import GTTS_ENABLE, GTTS_LANG, GTTS_TLD
    
    if GTTS_ENABLE and is_online():
        try:
            from gtts import gTTS
            tts = gTTS(text=text, lang=GTTS_LANG, tld=GTTS_TLD)
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
            cmd = f"{piper_binary} --model {model} --output_raw | aplay -D {ALSA_DEVICE} -r 22050 -f S16_LE -t raw -q"
            subprocess.run(cmd, shell=True) # subprocess.run IS blocking by default
            return

        # 3. Fallback to espeak
        subprocess.run(
            ["espeak", "-w", "/tmp/tts.wav", text], 
            check=False, stderr=subprocess.DEVNULL
        )
        play_audio_file("/tmp/tts.wav") # aplay is blocking
        
    except Exception as e:
        print(f"[tts] Error: {e}")

def live_stt_listen(recognizer, mic, timeout=None, phrase_time_limit=None) -> str:
    """
    Restore Google STT (Online).
    Accepts either a Microphone instance (opens/closes it) or an already open AudioSource.
    """
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return ""
    
    try:
        # Check if mic is actually a source (already open)
        # MUST check for active stream, otherwise we crash on closed mics
        is_open_source = False
        if isinstance(mic, sr.AudioSource) and hasattr(mic, "stream") and mic.stream is not None:
             is_open_source = True
             
        if is_open_source:
            source = mic
            # Listen without 'with' block (caller manages source)
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        else:
            # Traditional usage (opens/closes mic)
            with mic as source:
                audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        
        # Transcribe
# ... existing imports ...
import audioop
import math

# ... existing code ...

def _normalize_audio(audio_data: sr.AudioData, target_level=25000) -> sr.AudioData:
    """Normalize audio to target peak level (max 32767)."""
    try:
        raw_data = audio_data.get_raw_data()
        max_val = audioop.max(raw_data, 2)
        
        if max_val == 0:
            return audio_data
            
        factor = target_level / max_val
        factor = min(factor, 10.0) # Cap at 10x boost
        
        if factor > 1.05: # Only boost if significant
            boosted_raw = audioop.mul(raw_data, 2, factor)
            return sr.AudioData(boosted_raw, audio_data.sample_rate, audio_data.sample_width)
            
    except Exception as e:
        print(f"[audio] Normalization error: {e}")
        
    return audio_data

# ... live_stt_listen ...
def live_stt_listen(recognizer, mic, timeout=None, phrase_time_limit=None) -> str:
    # ... (same setup) ...
        # Transcribe
        try:
            return recognizer.recognize_google(audio)
        except sr.UnknownValueError:
            # RETRY ONCE WITH NORMALIZATION
            try:
                norm_audio = _normalize_audio(audio)
                # Check if it actually changed? (optimization: skip if factor ~1, but helper handles it)
                
                text = recognizer.recognize_google(norm_audio)
                print(f"[stt] (Normalized) Heard: '{text}'", flush=True)
                return text
            except Exception:
                # Still failed
                print("[stt] Speech detected but unintelligible (even after norm).", flush=True)
                return ""
# ... online_stt ...
def online_stt(audio_path: Path) -> str:
    # ...
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

# ... record_until_silence ...
def record_until_silence(out_path=LAST_AUDIO, silence_duration=1.0) -> Path:
    # ...
            # Save to WAV (Normalized)
            norm_audio = _normalize_audio(audio)
            with open(out_path, "wb") as f:
                f.write(norm_audio.get_wav_data())
            
            return out_path
            print(f"[stt] Google STT API Error: {e}", flush=True)
            return ""
            
    except sr.WaitTimeoutError:
        # print("[stt] Timeout: No speech detected.", flush=True) # Silenced per user request
        return "" # Silence
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
            try:
                return recognizer.recognize_google(audio)
            except sr.UnknownValueError:
                # RETRY ONCE WITH 5x BOOST
                import audioop
                raw_data = audio.get_raw_data()
                boosted_raw = audioop.mul(raw_data, 2, 5.0)
                boosted_audio = sr.AudioData(boosted_raw, audio.sample_rate, audio.sample_width)
                text = recognizer.recognize_google(boosted_audio)
                print(f"[stt] (Boosted 5x) Heard: '{text}'", flush=True)
                return text
                
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
            r.energy_threshold = 300 # Default starting point, dynamic adjustment is on by default
            r.dynamic_energy_threshold = True
            
            # Use configured index or default
            device_index = MIC_DEVICE_INDEX
            
            print(f"[record] Listening... (VAD enabled, silence={silence_duration}s)")
            with sr.Microphone(device_index=device_index) as source:
                # Fast calibration (optional, adds 0.5s latency but improves reliability)
                # r.adjust_for_ambient_noise(source, duration=0.5)
                
                # Listen automatically stops when silence is detected
                # phrase_time_limit ensures we don't record forever if noisy
                audio = r.listen(source, timeout=10, phrase_time_limit=15)
            
            # Save to WAV (Normalized to 75% max volume)
            import audioop
            import math
            raw_data = audio.get_raw_data()
            
            # Find peak
            max_val = audioop.max(raw_data, 2)
            if max_val > 0:
                # Target ~25000 (out of 32767)
                target = 25000
                factor = target / max_val
                
                # Cap factor at 10.0 to avoid boosting pure noise too much
                factor = min(factor, 10.0)
                
                if factor > 1.0:
                    try:
                        boosted_raw = audioop.mul(raw_data, 2, factor)
                        boosted_audio = sr.AudioData(boosted_raw, audio.sample_rate, audio.sample_width)
                        
                        # Only write boosted if successful
                        with open(out_path, "wb") as f:
                            f.write(boosted_audio.get_wav_data())
                            
                        print(f"[record] Normalized audio (Factor: {factor:.2f}, Peak: {max_val})")
                        return out_path
                    except Exception as e:
                        print(f"[record] Normalization failed: {e}")
            
            # Fallback to original
            with open(out_path, "wb") as f:
                f.write(audio.get_wav_data())
            
            return out_path
            
        except sr.WaitTimeoutError:
            print("[record] Timeout (silence)")
            return out_path # Likely empty or non-existent
        except Exception as e:
            print(f"[record] VAD Error: {e}")
            # Fallback to arecord below
            pass

    # Fallback to fixed duration arecord if sr fails or not available
    try:
        # Determine device
        device_arg = "default"
        if MIC_DEVICE_INDEX is not None and MIC_DEVICE_INDEX >= 0:
            device_arg = f"plughw:{MIC_DEVICE_INDEX},0"
        
        print("[record] Fallback: Recording 5s fixed...")
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

