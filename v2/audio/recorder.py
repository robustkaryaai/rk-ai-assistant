import os
import struct
import subprocess
import time
from pathlib import Path
from typing import Optional

from ctypes import CFUNCTYPE, c_char_p, c_int, cdll
from contextlib import contextmanager

try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_AVAILABLE = True
except ImportError:
    sr = None
    SPEECH_RECOGNITION_AVAILABLE = False

# WebRTC VAD — lightweight C-extension, very low CPU on Pi Zero
try:
    import webrtcvad
    WEBRTCVAD_AVAILABLE = True
except ImportError:
    webrtcvad = None
    WEBRTCVAD_AVAILABLE = False

# numpy for RMS calculation — usually pre-installed on Pi OS
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    np = None
    NUMPY_AVAILABLE = False

# Silence ALSA C-library error dumps
try:
    ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
    def _py_error_handler(filename, line, function, err, fmt):
        pass
    _c_error_handler = ERROR_HANDLER_FUNC(_py_error_handler)
except Exception:
    _c_error_handler = None

@contextmanager
def no_alsa_err():
    if _c_error_handler:
        try:
            asound = cdll.LoadLibrary('libasound.so')
            asound.snd_lib_error_set_handler(_c_error_handler)
            yield
            asound.snd_lib_error_set_handler(None)
            return
        except Exception:
            pass
    yield


def setup_microphone_volume():
    """Force hardware and software capture gain to maximum (far-field boost)."""
    controls = ["Capture", "Mic", "Internal Mic", "Digital", "Input", "Boost"]
    for control in controls:
        try:
            subprocess.run(["amixer", "sset", control, "100%"], capture_output=True)
            subprocess.run(["amixer", "sset", control, "cap"], capture_output=True)
        except Exception:
            pass
    try:
        # Boost PulseAudio capture source to 150% (digital pre-amp boost for far-field listening)
        subprocess.run(["pactl", "set-source-volume", "@DEFAULT_SOURCE@", "150%"], capture_output=True)
    except Exception:
        pass


# ─── Noise Gate + Soft Boost ──────────────────────────────────────────────────
# Replaces the old flat 35x amplifier.
# Strategy:
#   1. Compute RMS of the raw PCM block.
#   2. If RMS is below NOISE_FLOOR, the frame is just room noise — return silence
#      so Google STT doesn't try to decode hiss.
#   3. If RMS is above the floor, apply a gentle multiplier (capped at MAX_BOOST)
#      so distant speech gets louder without clipping.
#
# Why not 35x flat?  A flat 35x turns background hiss into a roar and sends
# Google STT a wall of noise.  The gate + soft-boost only amplifies when there
# is real energy in the signal, keeping the SNR clean.
# ─────────────────────────────────────────────────────────────────────────────

NOISE_FLOOR_RMS  = 150   # RMS counts below this = pure room noise, gate it out
TARGET_RMS       = 3000  # We aim to lift speech to roughly this RMS level
MAX_BOOST        = 8.0   # Never amplify more than 8× (prevents noise explosion)
PEAK_CLIP_LIMIT  = 31000 # Hard ceiling to avoid int16 overflow / distortion


def _smart_boost(audio_data):
    """
    Noise-gate + RMS-proportional soft boost for far-field speech.

    - Below NOISE_FLOOR_RMS  → return silence (gates pure noise frames)
    - Above NOISE_FLOOR_RMS  → boost proportionally up to MAX_BOOST
    - Always hard-clips at ±PEAK_CLIP_LIMIT to prevent distortion

    Falls back gracefully when numpy or sr are unavailable.
    """
    if not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return audio_data

    try:
        raw = audio_data.get_raw_data()
        n_samples = len(raw) // 2  # 16-bit = 2 bytes per sample

        if n_samples == 0:
            return audio_data

        if NUMPY_AVAILABLE:
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(samples ** 2)))
        else:
            # Pure-Python RMS fallback (slower but works without numpy)
            total = sum(struct.unpack_from('<h', raw, i * 2)[0] ** 2 for i in range(n_samples))
            rms = (total / n_samples) ** 0.5

        # Gate: if it's basically silence / noise, send silence to STT
        if rms < NOISE_FLOOR_RMS:
            silence = b'\x00' * len(raw)
            return sr.AudioData(silence, audio_data.sample_rate, audio_data.sample_width)

        # Soft boost: scale toward TARGET_RMS, cap at MAX_BOOST
        boost = min(TARGET_RMS / max(rms, 1.0), MAX_BOOST)

        if boost <= 1.05:
            return audio_data  # Already loud enough, no change needed

        if NUMPY_AVAILABLE:
            boosted = np.clip(samples * boost, -PEAK_CLIP_LIMIT, PEAK_CLIP_LIMIT)
            boosted_raw = boosted.astype(np.int16).tobytes()
        else:
            import audioop
            boosted_raw = audioop.mul(raw, 2, int(boost))

        return sr.AudioData(boosted_raw, audio_data.sample_rate, audio_data.sample_width)

    except Exception:
        return audio_data


# ─── WebRTC VAD Audio Filter ──────────────────────────────────────────────────
# WebRTC VAD operates on fixed-size PCM frames: 10ms, 20ms, or 30ms at 16kHz.
# We scan the full recording frame-by-frame and keep only the frames that VAD
# classifies as speech.  This strips silence/noise between and around words
# before the bytes are sent to Google STT, giving it a much cleaner signal.
#
# Aggressiveness 2 = balanced (0=least, 3=most aggressive noise rejection).
# On Pi Zero this runs in ~0.1ms per frame — effectively free.
# ─────────────────────────────────────────────────────────────────────────────

VAD_AGGRESSIVENESS   = 2    # 0–3; 2 = good balance for indoor far-field
VAD_FRAME_MS         = 30   # ms per frame — 30ms chunks at 16kHz = 480 samples
VAD_SAMPLE_RATE      = 16000
VAD_FRAME_BYTES      = VAD_FRAME_MS * VAD_SAMPLE_RATE * 2 // 1000  # = 960 bytes
# Minimum ratio of speech frames to keep — if fewer than this, treat as noise
VAD_MIN_SPEECH_RATIO = 0.10  # At least 10% of frames must be speech


def _vad_filter(audio_data):
    """
    Strip non-speech frames from an AudioData block using WebRTC VAD.

    Returns a new AudioData containing only the speech frames, or the original
    if VAD is not available or there isn't enough speech detected.
    """
    if not WEBRTCVAD_AVAILABLE or not SPEECH_RECOGNITION_AVAILABLE or sr is None:
        return audio_data  # Graceful no-op

    try:
        raw = audio_data.get_raw_data()
        vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

        speech_frames = []
        total_frames  = 0

        offset = 0
        while offset + VAD_FRAME_BYTES <= len(raw):
            frame = raw[offset: offset + VAD_FRAME_BYTES]
            try:
                is_speech = vad.is_speech(frame, VAD_SAMPLE_RATE)
            except Exception:
                is_speech = True  # If VAD errors on a frame, keep it
            if is_speech:
                speech_frames.append(frame)
            total_frames += 1
            offset += VAD_FRAME_BYTES

        if total_frames == 0:
            return audio_data

        speech_ratio = len(speech_frames) / total_frames
        if speech_ratio < VAD_MIN_SPEECH_RATIO:
            # Basically all noise — return the original so STT can still try
            return audio_data

        filtered_raw = b''.join(speech_frames)
        return sr.AudioData(filtered_raw, audio_data.sample_rate, audio_data.sample_width)

    except Exception:
        return audio_data


class AudioRecorder:
    """
    Robust Audio Capture & STT for Pi Zero W.
    Combines v1's proven hardware gain + audio normalization + Google STT
    with v2's clean architecture and cloud fallback.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.record_path = data_dir / "last_command.wav"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.is_hardware_muted = False

        # Set hardware mic volume on startup
        setup_microphone_volume()

        self._recognizer: Optional[sr.Recognizer] = None
        self._mic: Optional[sr.Microphone] = None
        if SPEECH_RECOGNITION_AVAILABLE:
            try:
                self._recognizer = sr.Recognizer()
                # 🚀 Far-Field Sensitivity: sensitive 50 base threshold + dynamic tracking
                self._recognizer.energy_threshold = 50
                self._recognizer.dynamic_energy_threshold = True
                self._recognizer.dynamic_energy_ratio = 1.3
                self._recognizer.pause_threshold = 1.1
                self._recognizer.phrase_threshold = 0.1   # Catch far away speech instantly
                self._recognizer.non_speaking_duration = 0.8
                self._mic = sr.Microphone(sample_rate=16000)
            except Exception as e:
                print(f"[recorder] Error initializing SpeechRecognition: {e}", flush=True)

    def calibrate_once(self):
        """Calibrate ambient noise with 100% hardware gain set."""
        setup_microphone_volume()
        if self._recognizer and self._mic:
            try:
                print("🎙️ [STT] Calibrating microphone for room noise (1s)...", flush=True)
                with self._mic as source:
                    self._recognizer.adjust_for_ambient_noise(source, duration=0.8)
                # Keep floor ultra-sensitive (50) for distant speech
                self._recognizer.energy_threshold = max(self._recognizer.energy_threshold, 50)
                print(f"🎙️ [STT] Baseline energy threshold: {self._recognizer.energy_threshold:.0f}", flush=True)
            except Exception as e:
                print(f"[STT] Calibration notice: {e}", flush=True)

    def record_command(self, duration: int = 10, silence_duration: float = 1.2) -> Optional[Path]:
        """
        Record user speech using speech_recognition (v1 method) with audio boost.
        Returns Path to WAV if speech captured, None if silence.
        """
        if self.is_hardware_muted:
            return None

        if self.record_path.exists():
            try:
                self.record_path.unlink()
            except Exception:
                pass

        if self._recognizer and self._mic:
            try:
                # Keep pause threshold generous (1.8s) so natural mid-sentence pauses aren't cut short
                self._recognizer.pause_threshold = max(silence_duration, 1.8)
                self._recognizer.non_speaking_duration = 1.0
                with no_alsa_err():
                    with self._mic as source:
                        # phrase_time_limit allows speaking full long sentences (12s)
                        audio = self._recognizer.listen(source, timeout=6, phrase_time_limit=max(duration, 12))

                # 1. Strip non-speech frames (WebRTC VAD) — cleans signal before boost
                audio = _vad_filter(audio)
                # 2. Noise gate + soft RMS boost — replaces old flat 35x amplifier
                audio = _smart_boost(audio)

                with open(self.record_path, "wb") as f:
                    f.write(audio.get_wav_data())

                if self.record_path.exists() and self.record_path.stat().st_size > 1500:
                    return self.record_path

            except sr.WaitTimeoutError:
                # Normal silence — return None so loop continues
                return None
            except Exception as e:
                # Other audio error — fall through to arecord
                pass

        # Native ALSA arecord fallback
        cmd = [
            "arecord",
            "-D", "default",
            "-f", "S16_LE",
            "-r", "16000",
            "-c", "1",
            "-d", str(duration),
            "-q",
            str(self.record_path)
        ]
        try:
            subprocess.run(cmd, check=True, timeout=duration + 3)
            if self.record_path.exists() and self.record_path.stat().st_size > 1500:
                return self.record_path
        except Exception:
            pass

        return None

    def transcribe(self, client=None) -> str:
        """
        Transcribe captured audio:
        1. Google STT with normalized audio (exact v1 engine that worked great).
        2. Backend Cloud STT fallback.
        """
        if not self.record_path.exists():
            return ""

        # 1. Primary: Direct Google STT with dual language fallback (en-IN -> en-US)
        if SPEECH_RECOGNITION_AVAILABLE:
            try:
                r = sr.Recognizer()
                with sr.AudioFile(str(self.record_path)) as source:
                    audio = r.record(source)
                    # 1. VAD filter — strip silence/noise frames first
                    audio = _vad_filter(audio)
                    # 2. Noise gate + soft boost — clean amplification
                    audio = _smart_boost(audio)
                    text = ""
                    for lang in ["en-IN", "en-US"]:
                        try:
                            text = r.recognize_google(audio, language=lang).strip()
                            if text:
                                break
                        except sr.UnknownValueError:
                            continue
                    if text:
                        print(f"🔤 [STT] Recognized: '{text}'", flush=True)
                        return text
            except sr.UnknownValueError:
                pass  # Audio was background noise / unintelligible
            except sr.RequestError as e:
                print(f"[STT] Google STT request error: {e}", flush=True)
            except Exception as e:
                print(f"[STT] Local STT error: {e}", flush=True)

        # 2. Secondary fallback: Backend Cloud Whisper
        if client:
            try:
                audio_bytes = self.record_path.read_bytes()
                res = client.send_audio(audio_bytes)
                text = res.get("text", "").strip()
                if text:
                    print(f"☁️ [STT] Cloud: '{text}'", flush=True)
                    return text
            except Exception as e:
                print(f"[STT] Cloud STT error: {e}", flush=True)

        return ""
