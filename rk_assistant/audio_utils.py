"""
Audio utilities for Pi Zero W.

Uses small-footprint dependencies:
- sounddevice for capture (wraps ALSA)
- pocketsphinx for offline wake/STT if available
- espeak for TTS (command-line to avoid heavy libs)
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import sounddevice as sd  # type: ignore

from .config import (
    CHANNELS,
    LAST_AUDIO,
    MAX_RECORD_SECONDS,
    SAMPLE_RATE,
    POCKETSPHINX_MODEL_DIR,
    WAKE_WORD,
)

try:
    from pocketsphinx import LiveSpeech  # type: ignore
    POCKETSPHINX_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    LiveSpeech = None
    POCKETSPHINX_AVAILABLE = False

try:
    import speech_recognition as sr  # type: ignore
    SPEECH_RECOGNITION_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    sr = None
    SPEECH_RECOGNITION_AVAILABLE = False

try:
    import numpy as np  # type: ignore
    NUMPY_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    np = None
    NUMPY_AVAILABLE = False


def _safe_print(msg: str) -> None:
    print(msg, flush=True)


def load_pocketsphinx_decoder() -> bool:
    """Check if PocketSphinx is available and ready to use."""
    if not POCKETSPHINX_AVAILABLE or LiveSpeech is None:
        _safe_print("[audio] PocketSphinx not installed; wake/STT offline disabled.")
        return False
    try:
        # Test if we can create a LiveSpeech instance
        # This will use system-installed models by default
        test_speech = LiveSpeech(verbose=False, no_search=True)
        del test_speech
        return True
    except Exception as exc:  # pragma: no cover
        _safe_print(f"[audio] PocketSphinx available but failed to initialize: {exc}")
        return False


def wait_for_wake_word(decoder_available: bool, wake_word: str = WAKE_WORD, max_seconds: float | None = None) -> bool:
    """
    Stream audio until wake word is detected.
    Returns True when wake word heard, False on error/timeout.
    """
    if not decoder_available or LiveSpeech is None:
        _safe_print("[audio] Wake detection unavailable (no decoder).")
        time.sleep(1)
        return False

    # Configure keyword spotting for wake word
    config = {
        'verbose': False,
        'sampling_rate': SAMPLE_RATE,
        'buffer_size': 2048,
        'no_search': False,
        'full_utt': False,
        'keyphrase': wake_word.lower(),
        'kws_threshold': 1e-20,  # Lower threshold for better detection
    }
    
    # Add model path if specified
    model_path = POCKETSPHINX_MODEL_DIR
    if model_path and Path(model_path).exists():
        config['hmm'] = str(Path(model_path) / 'acoustic-model')
        config['dict'] = str(Path(model_path) / 'pronunciation-dictionary.dict')
    try:
        speech = LiveSpeech(**config)
        _safe_print(f"[wake] Listening for wake word '{wake_word}' ...")
        start = time.time()
        for phrase in speech:
            if max_seconds and (time.time() - start) > max_seconds:
                return False
            text = str(phrase).strip().lower()
            if wake_word.lower() in text:
                _safe_print("[wake] Wake word detected.")
                return True
            if time.time() - start > 300:  # reset every 5 minutes
                start = time.time()
    except Exception as exc:
        _safe_print(f"[wake] Error in wake word detection: {exc}")
        return False
    return False


def record_audio(out_path: Path = LAST_AUDIO, seconds: int = MAX_RECORD_SECONDS) -> Path:
    """Record audio to a WAV file with a strict time cap."""
    duration = max(1, min(seconds, MAX_RECORD_SECONDS))
    _safe_print(f"[record] Recording for {duration}s -> {out_path}")
    audio = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
    )
    sd.wait()

    import wave

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    _safe_print("[record] Saved.")
    return out_path


def record_until_silence(out_path: Path = LAST_AUDIO, silence_duration: float = 2.0, silence_threshold: int = 500) -> Path:
    """
    Record audio until silence is detected for specified duration.
    
    Args:
        out_path: Path to save audio file
        silence_duration: Seconds of silence to stop recording (default 2.0)
        silence_threshold: Amplitude threshold for silence detection (default 500)
    
    Returns:
        Path to recorded audio file
    """
    if not NUMPY_AVAILABLE or np is None:
        _safe_print("[record] NumPy not available, falling back to fixed-time recording")
        return record_audio(out_path, seconds=10)
    
    import wave
    
    _safe_print(f"[record] Recording until {silence_duration}s of silence...")
    
    chunk_duration = 0.1  # 100ms chunks
    chunk_samples = int(SAMPLE_RATE * chunk_duration)
    silence_chunks_needed = int(silence_duration / chunk_duration)
    
    recorded_chunks = []
    silence_counter = 0
    max_duration = MAX_RECORD_SECONDS  # Safety cap
    total_time = 0
    
    try:
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype='int16',
            blocksize=chunk_samples
        )
        stream.start()
        _safe_print("[record] Listening... (speak now)")
        
        while total_time < max_duration:
            chunk, overflowed = stream.read(chunk_samples)
            recorded_chunks.append(chunk.copy())
            
            # Calculate RMS (root mean square) to detect volume
            rms = np.sqrt(np.mean(chunk**2))
            
            if rms < silence_threshold:
                silence_counter += 1
                if silence_counter >= silence_chunks_needed:
                    _safe_print(f"[record] Silence detected for {silence_duration}s, stopping...")
                    break
            else:
                silence_counter = 0  # Reset on sound detection
            
            total_time += chunk_duration
        
        stream.stop()
        stream.close()
        
        # Combine all chunks
        audio_data = np.concatenate(recorded_chunks, axis=0)
        
        # Save to WAV file
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_data.tobytes())
        
        _safe_print(f"[record] Saved {total_time:.1f}s of audio")
        return out_path
        
    except Exception as exc:
        _safe_print(f"[record] Error during recording: {exc}")
        # Return empty file on error
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
        return out_path


def quick_stt(decoder_available: bool, seconds: float = 3.0) -> str:
    """Short transcription for quick commands (online check)."""
    if not decoder_available or LiveSpeech is None:
        return ""
    
    config = {
        'verbose': False,
        'sampling_rate': SAMPLE_RATE,
        'buffer_size': 2048,
        'no_search': False,
        'full_utt': False,
    }
    
    # Add model path if specified
    model_path = POCKETSPHINX_MODEL_DIR
    if model_path and Path(model_path).exists():
        config['hmm'] = str(Path(model_path) / 'acoustic-model')
        config['dict'] = str(Path(model_path) / 'pronunciation-dictionary.dict')
    
    try:
        speech = LiveSpeech(**config)
        _safe_print(f"[stt] Quick listen {seconds}s")
        end_time = time.time() + seconds
        text_parts = []
        for phrase in speech:
            if time.time() >= end_time:
                break
            text = str(phrase).strip()
            if text:
                text_parts.append(text)
        return " ".join(text_parts)
    except Exception as exc:
        _safe_print(f"[stt] Error in quick STT: {exc}")
        return ""


def speak(text: str, voice: str = "en") -> None:
    """Speak via espeak (fast, low RAM)."""
    if not text:
        return
    cmd = ["espeak", f"-v{voice}", text]
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        _safe_print("[tts] espeak not installed.")


def synthesize_to_wav(text: str, out_path: Path) -> Optional[Path]:
    """Render TTS to WAV using espeak. Returns file path or None."""
    if not text:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["espeak", "-w", str(out_path), text], check=True)
        return out_path
    except FileNotFoundError:
        _safe_print("[tts] espeak not installed.")
    except subprocess.CalledProcessError:
        _safe_print("[tts] espeak failed to synthesize.")
    return None


def play_audio_url(url: str) -> subprocess.Popen | None:
    """
    Stream audio URL using mpg123 (lightweight).
    Returns Popen handle for control.
    """
    if not url:
        return None
    try:
        proc = subprocess.Popen(["mpg123", "-q", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _safe_print(f"[music] Playing {url}")
        return proc
    except FileNotFoundError:
        _safe_print("[music] mpg123 not installed.")
        return None


def stop_process(proc: Optional[subprocess.Popen]) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def set_volume(delta: int) -> None:
    """Adjust ALSA PCM volume by delta (-20..+20)."""
    delta = max(-50, min(50, delta))
    sign = "+" if delta >= 0 else ""
    try:
        subprocess.run(["amixer", "set", "PCM", f"{sign}{delta}%"], check=False)
    except FileNotFoundError:
        _safe_print("[volume] amixer not available.")


def online_stt(audio_path: Path) -> str:
    """
    Transcribe audio using Google Speech Recognition API (online).
    Falls back to PocketSphinx if offline or API fails.
    """
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        _safe_print("[stt] SpeechRecognition not available, using PocketSphinx fallback")
        if not POCKETSPHINX_AVAILABLE:
            return ""
        return _pocketsphinx_transcribe(audio_path)
    
    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(str(audio_path)) as source:
            audio = recognizer.record(source)
        
        # Try Google Speech Recognition first (requires internet)
        try:
            text = recognizer.recognize_google(audio)
            _safe_print(f"[stt] Google recognized: {text}")
            return text
        except sr.UnknownValueError:
            _safe_print("[stt] Google could not understand audio")
            return ""
        except sr.RequestError as e:
            _safe_print(f"[stt] Google API error: {e}, falling back to PocketSphinx")
            # Fall back to PocketSphinx if online API fails
            if POCKETSPHINX_AVAILABLE:
                return _pocketsphinx_transcribe(audio_path)
            return ""
    except Exception as exc:
        _safe_print(f"[stt] Error in online STT: {exc}")
        return ""


def _pocketsphinx_transcribe(audio_path: Path) -> str:
    """Transcribe audio file using PocketSphinx (offline fallback)."""
    if not POCKETSPHINX_AVAILABLE or LiveSpeech is None:
        return ""
    
    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(str(audio_path)) as source:
            audio = recognizer.record(source)
        text = recognizer.recognize_sphinx(audio)
        _safe_print(f"[stt] PocketSphinx recognized: {text}")
        return text
    except sr.UnknownValueError:
        _safe_print("[stt] PocketSphinx could not understand audio")
        return ""
    except Exception as exc:
        _safe_print(f"[stt] Error in PocketSphinx transcription: {exc}")
        return ""


