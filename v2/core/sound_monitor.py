"""
Sound Monitor for Baby Cry & Emergency Loud Noise Detection.
Ultra-lightweight DSP designed for single-core ARMv6 (Raspberry Pi Zero W).
Runs only when enabled (opt-in) or during designated monitoring cycles.
Gated against TTS speech feedback.
"""

import time
import math
import struct
import numpy as np
from pathlib import Path
from typing import Optional

class SoundEventMonitor:
    # Infant cry acoustics: fundamental pitch sits between 350Hz and 650Hz with rich harmonics > 1kHz
    CRY_F0_RANGE = (320, 680)
    CRY_HARMONIC_MIN_RATIO = 0.30   # At least 30% of energy above 1000 Hz
    ALERT_COOLDOWN = 60.0           # 60s cooldown to prevent notification floods

    def __init__(self, client=None, tts=None):
        self.client = client
        self.tts = tts
        self.enabled = False        # Opt-in: only check when baby monitor mode is active
        self.tts_active = False     # Gate: never trigger on assistant's own voice/chime
        self.last_shout_alert = 0.0
        self.last_cry_alert = 0.0

    def check_audio_file(self, wav_path: Path) -> Optional[str]:
        """
        Fast frequency-domain analysis:
        1. Gated by enabled flag and tts_active state.
        2. Computes RMS energy, FFT dominant pitch, and spectral brightness.
        """
        if not self.enabled or self.tts_active:
            return None

        if not wav_path or not Path(wav_path).exists() or Path(wav_path).stat().st_size < 32000:
            # Need at least ~1 second of 16kHz audio to accurately determine pitch
            return None

        try:
            with open(wav_path, "rb") as f:
                raw_bytes = f.read()

            samples_bytes = raw_bytes[44:]
            num_samples = len(samples_bytes) // 2
            if num_samples < 16000:
                return None

            # Convert to numpy array for fast vector math
            samples = np.frombuffer(samples_bytes[:num_samples * 2], dtype=np.int16).astype(np.float32)
            rms = np.sqrt(np.mean(samples ** 2))
            now = time.time()

            # Extreme loud crash/shout detector (> 16000 RMS)
            if rms > 16000:
                if (now - self.last_shout_alert) > self.ALERT_COOLDOWN:
                    self.last_shout_alert = now
                    print(f"⚠️ [SOUND MONITOR] Loud noise detected (RMS: {rms:.0f})!", flush=True)
                    self.notify_backend("shouting_detected", {"rms": float(rms)})
                    return "shouting"

            # Check for baby cry if volume is sufficient
            if rms < 3500:
                return None

            sr = 16000
            chunk_len = 3200   # 200ms per window
            num_chunks = min(len(samples) // chunk_len, 10)
            cry_chunks = 0

            for i in range(num_chunks):
                chunk = samples[i * chunk_len : (i + 1) * chunk_len]
                c_rms = np.sqrt(np.mean(chunk ** 2))
                if c_rms < 3000:
                    continue

                # Fast Hanning FFT
                windowed = chunk * np.hanning(len(chunk))
                fft_vals = np.abs(np.fft.rfft(windowed))
                freqs = np.fft.rfftfreq(len(chunk), d=1.0 / sr)

                # Find dominant pitch peak in voice range (150 - 1000 Hz)
                valid_mask = (freqs >= 150) & (freqs <= 1000)
                if not np.any(valid_mask):
                    continue

                peak_idx = np.argmax(fft_vals[valid_mask])
                peak_f0 = freqs[valid_mask][peak_idx]

                # Spectral brightness: energy ratio above 1000 Hz
                total_energy = np.sum(fft_vals ** 2) + 1e-9
                high_energy = np.sum((fft_vals[freqs >= 1000]) ** 2)
                hf_ratio = high_energy / total_energy

                # Check if this 200ms window matches infant cry pitch and harmonic signature
                if self.CRY_F0_RANGE[0] <= peak_f0 <= self.CRY_F0_RANGE[1] and hf_ratio >= self.CRY_HARMONIC_MIN_RATIO:
                    cry_chunks += 1

            # Require sustained cry: at least 4 chunks (~0.8s) out of 10
            if cry_chunks >= 4 and (now - self.last_cry_alert) > self.ALERT_COOLDOWN:
                self.last_cry_alert = now
                print(f"👶 [SOUND MONITOR] Baby cry verified ({cry_chunks}/{num_chunks} chunks, F0 in range)", flush=True)
                self.notify_backend("baby_cry_detected", {"rms": float(rms), "cry_chunks": cry_chunks})
                return "baby_cry"

        except Exception as e:
            # Fall through silently if format parsing fails
            pass

        return None

    def notify_backend(self, event_type: str, details: dict):
        """Dispatches event to backend which sends mobile push notifications."""
        if self.client:
            try:
                url = f"{self.client.base_url}/device/{self.client.slug}/alert"
                self.client.session.post(url, json={"event": event_type, "details": details, "timestamp": time.time()}, timeout=3)
            except Exception as e:
                print(f"[sound-monitor] Backend alert error: {e}")
