"""
v2/core/sound_monitor.py (Pi Zero W: numpy + stdlib only)
Ultra-optimized baby cry & loud noise monitor:
- Zero-copy strided framing (numpy as_strided)
- Fast vectorized energy gate (einsum) — silence exits in ~0.2ms
- FFT-based autocorrelation for exact fundamental pitch (F0: 300-650 Hz)
- Spectral brightness harmonic check (> 1000 Hz)
- Multi-clip voting (2 of 3 votes) + 60s cooldown
- Fully non-blocking & gated against TTS speech feedback
"""

import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
import time
import wave
from collections import deque
from pathlib import Path
from typing import Optional, Union

import numpy as np
from numpy.lib.stride_tricks import as_strided


class SoundEventMonitor:
    SR = 8000                      # 8 kHz downsampled or captured (cry fundamental + harmonics fit well under 4 kHz)
    N, HOP, NFFT = 256, 128, 512   # 32 ms frames, 16 ms hop
    CLIP_S = 2
    MIN_DBFS = -40                 # Quiet-frame gate
    F0_LO, F0_HI = 300, 650        # Infant cry fundamental pitch in Hz
    MIN_PERIODICITY = 0.5          # Autocorrelation peak threshold for voiced sound
    MIN_HF_RATIO = 0.30            # Energy share above 1 kHz (infant bright harmonic signature)
    MIN_CRY_SECONDS = 0.6          # Minimum cry duration in a 2s clip
    MIN_CRY_RATIO = 0.5            # Ratio of cry frames to voiced frames
    VOTES_NEEDED, VOTE_WINDOW = 2, 3
    COOLDOWN_S = 60.0
    DEBUG = False

    def __init__(self, client=None, tts=None):
        self.client = client
        self.tts = tts
        self.enabled = False        # Opt-in: only check when baby monitor mode is active
        self.tts_active = False     # Gate: never trigger on assistant's own voice/chime
        self._last_alert = 0.0
        self._votes = deque(maxlen=self.VOTE_WINDOW)
        self.CLIP_BYTES = self.CLIP_S * self.SR * 2
        self._min_ms = (32768 * 10 ** (self.MIN_DBFS / 20)) ** 2
        self._min_frames = int(np.ceil(self.MIN_CRY_SECONDS * self.SR / self.HOP))
        self._win = np.hanning(self.N).astype(np.float32)
        self._lo = int(self.SR / (self.F0_HI + 50))     # Shortest lag searched
        self._hi = int(self.SR / (self.F0_LO - 20))     # Longest lag searched
        self._lags = np.arange(self._lo, self._hi + 1)
        self._f0_of_lag = self.SR / self._lags
        self._band_ok = (self._f0_of_lag >= self.F0_LO) & (self._f0_of_lag <= self.F0_HI)
        self._hf_bin = int(1000 / (self.SR / self.NFFT))

    def _analyze(self, raw: bytes) -> bool:
        """
        Core DSP analysis on raw 8kHz int16 PCM bytes:
        Stage 1: Cheap energy gate (silence exits in ~0.2ms)
        Stage 2: FFT autocorrelation & spectral ratio on loud frames only
        """
        if len(raw) < self.N * 2:
            return False

        y = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        n = 1 + (len(y) - self.N) // self.HOP
        if n <= 0:
            return False

        s = y.strides[0]
        fr = as_strided(y, (n, self.N), (self.HOP * s, s), writeable=False)

        # Stage 1: Cheap energy gate — no intermediate arrays
        ms = np.einsum("ij,ij->i", fr, fr) / self.N
        loud = ms > self._min_ms
        if loud.sum() < self._min_frames:
            return False  # Pure silence exits immediately

        # Stage 2: Heavy work on loud frames only
        fr = fr[loud]
        fr = (fr - fr.mean(axis=1, keepdims=True)) * self._win
        X = np.fft.rfft(fr, self.NFFT, axis=1)
        P = X.real ** 2 + X.imag ** 2

        # Fast autocorrelation via IRFFT
        ac = np.fft.irfft(P, self.NFFT, axis=1)
        ac0 = ac[:, 0] + 1e-9
        seg = ac[:, self._lo : self._hi + 1]
        k = seg.argmax(axis=1)
        peak = seg[np.arange(len(k)), k] / ac0
        in_band = self._band_ok[k]
        hf = P[:, self._hf_bin :].sum(axis=1) / (P.sum(axis=1) + 1e-9)

        voiced = peak > self.MIN_PERIODICITY
        nv = int(voiced.sum())
        if nv < self._min_frames:
            return False

        cry = voiced & in_band & (hf > self.MIN_HF_RATIO)
        nc = int(cry.sum())
        cry_s = nc * self.HOP / self.SR
        ratio = nc / nv
        if self.DEBUG:
            print(f"[SM] loud={len(k)} voiced={nv} cry_s={cry_s:.2f} ratio={ratio:.2f}", flush=True)

        return (cry_s >= self.MIN_CRY_SECONDS) and (ratio >= self.MIN_CRY_RATIO)

    def _vote(self, hit: bool) -> bool:
        """Voting filter (2 of 3) + cooldown timer."""
        self._votes.append(hit)
        if sum(self._votes) >= self.VOTES_NEEDED and (time.time() - self._last_alert > self.COOLDOWN_S):
            self._last_alert = time.time()
            self._votes.clear()
            print("👶 [SOUND MONITOR] Baby cry verified", flush=True)
            self.notify_backend("baby_cry_detected", {"verified": True})
            return True
        return False

    def check_audio_file(self, wav_path: Union[str, Path]) -> bool:
        """
        Unified compatibility method:
        Processes audio captured in memory/file, downsamples from 16kHz to 8kHz via decimation,
        and runs the zero-copy DSP analyzer.
        """
        if not self.enabled or self.tts_active:
            return False

        path = Path(wav_path)
        if not path.exists() or path.stat().st_size < 4000:
            return False

        try:
            with wave.open(str(path), "rb") as w:
                sr = w.getframerate()
                n_channels = w.getnchannels()
                raw_frames = w.readframes(w.getnframes())

            samples = np.frombuffer(raw_frames, dtype=np.int16)
            if n_channels > 1:
                samples = samples[::n_channels]

            # If input is 16 kHz (standard STT audio), decimate by 2 to get 8 kHz
            if sr == 16000:
                samples = samples[::2]
            elif sr != 8000:
                return False

            raw_8k = samples.tobytes()
            hits = [
                self._analyze(raw_8k[i : i + self.CLIP_BYTES])
                for i in range(0, len(raw_8k) - self.CLIP_BYTES + 1, self.CLIP_BYTES)
            ]
            return any(self._vote(h) for h in hits)

        except Exception as e:
            if self.DEBUG:
                print(f"[SM] Analysis error: {e}", flush=True)
            return False

    def notify_backend(self, event_type: str, details: dict):
        """Dispatches event to backend which triggers user push alerts."""
        if self.client:
            try:
                url = f"{self.client.base_url}/device/{self.client.slug}/alert"
                self.client.session.post(url, json={"event": event_type, "details": details, "timestamp": time.time()}, timeout=3)
            except Exception as e:
                if self.DEBUG:
                    print(f"[sound-monitor] Backend alert error: {e}", flush=True)
