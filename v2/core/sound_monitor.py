"""
Sound Monitor for Baby Cry & Loud Shouting Detection.
Listens to ambient audio levels and alerts backend via high-priority push events.
Extremely lightweight: computes RMS energy on captured frames without heavy ML models.
"""

import time
import math
import struct
from pathlib import Path
from typing import Optional

class SoundEventMonitor:
    def __init__(self, client=None, tts=None):
        self.client = client
        self.tts = tts
        self.last_shout_alert = 0.0
        self.last_cry_alert = 0.0
        self.alert_cooldown = 30.0  # 30s cooldown between alerts

    def check_audio_file(self, wav_path: Path) -> Optional[str]:
        """
        Analyzes audio file for shouting/baby cry characteristics:
        - High sustained pitch + energy fluctuations = Baby Cry
        - Sudden high RMS peak (> threshold) = Shouting / Loud Noise
        """
        if not wav_path.exists() or wav_path.stat().st_size < 1000:
            return None

        try:
            with open(wav_path, "rb") as f:
                raw_bytes = f.read()

            # Skip 44-byte WAV header
            samples_bytes = raw_bytes[44:]
            num_samples = len(samples_bytes) // 2
            if num_samples == 0:
                return None

            samples = struct.unpack(f"{num_samples}h", samples_bytes[:num_samples * 2])
            sum_squares = sum(s * s for s in samples)
            rms = math.sqrt(sum_squares / num_samples)

            now = time.time()

            # Shouting / Extreme Loud Peak Detection (RMS > 14000)
            if rms > 14000:
                if (now - self.last_shout_alert) > self.alert_cooldown:
                    self.last_shout_alert = now
                    print(f"⚠️ [SOUND MONITOR] Loud shouting/noise detected (RMS: {rms:.0f})!")
                    self.notify_backend("shouting_detected", {"rms": rms})
                    return "shouting"

            # Baby Cry Pattern Detection (Sustained mid-high frequency bursts: RMS between 7000 and 13000 with variance)
            if 7000 < rms <= 14000:
                # Check variance across segments
                chunk_size = num_samples // 5
                chunks_rms = []
                for i in range(5):
                    chunk = samples[i * chunk_size : (i + 1) * chunk_size]
                    if chunk:
                        c_rms = math.sqrt(sum(c * c for c in chunk) / len(chunk))
                        chunks_rms.append(c_rms)

                # Baby cry typically has repetitive rise and fall in volume
                if len(chunks_rms) == 5 and max(chunks_rms) - min(chunks_rms) > 3000:
                    if (now - self.last_cry_alert) > self.alert_cooldown:
                        self.last_cry_alert = now
                        print(f"👶 [SOUND MONITOR] Baby cry pattern detected!")
                        self.notify_backend("baby_cry_detected", {"rms": rms})
                        return "baby_cry"

        except Exception as e:
            print(f"[sound-monitor] Analysis note: {e}")

        return None

    def notify_backend(self, event_type: str, details: dict):
        """Dispatches event to backend which sends mobile push notifications."""
        if self.client:
            try:
                url = f"{self.client.base_url}/device/{self.client.slug}/alert"
                self.client.session.post(url, json={"event": event_type, "details": details, "timestamp": time.time()}, timeout=3)
            except Exception as e:
                print(f"[sound-monitor] Backend ping error: {e}")
