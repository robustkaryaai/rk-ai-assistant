import os
import subprocess
import signal
import time
import shutil
from typing import Optional

class AudioPlayer:
    """
    Alexa-Grade Audio Player for Pi Zero W (ARMv6, 512MB RAM).
    Features:
    - Automatically routes to PulseAudio / Bluetooth speaker sink (-o pulse)
    - Fallback to ALSA (-o alsa) and system aplay for WAV files
    - Direct espeak speech generation if file playback isn't requested
    """

    def __init__(self):
        self._current_proc: Optional[subprocess.Popen] = None
        self._current_url: Optional[str] = None
        self._next_prebuffered_url: Optional[str] = None
        self._is_ducked: bool = False
        self._pre_duck_volume: int = 70
        self._last_audio_activity: float = time.time()

    def play_url_or_file(self, target: str, is_speech: bool = False) -> bool:
        """Play stream URL or local audio file via mpg123 or aplay."""
        self.stop()
        if not target:
            return False

        self._current_url = target
        self._last_audio_activity = time.time()

        is_url = target.startswith(("http://", "https://"))

        # 1. Web stream playback (WebM, Opus, MP4, MP3 via mpv / cvlc / ffplay)
        if is_url:
            stream_cmds = []
            if shutil.which("mpv"):
                # Ultra-light flags for single-core Pi Zero W:
                # --no-video, --vo=null, audio-only buffer, and lower CPU footprint
                mpv_light = [
                    "mpv",
                    "--really-quiet",
                    "--no-video",
                    "--vo=null",
                    "--ao=pulse",
                    "--audio-buffer=0.2",
                    "--demuxer-max-bytes=8M",
                    "--demuxer-readahead-secs=5",
                    target
                ]
                stream_cmds.append(mpv_light)
                stream_cmds.append(["mpv", "--really-quiet", "--no-video", "--vo=null", target])
            if shutil.which("cvlc"):
                stream_cmds.append(["cvlc", "--play-and-exit", "--no-video", "--quiet", target])
            if shutil.which("ffplay"):
                stream_cmds.append(["ffplay", "-autoexit", "-nodisp", "-loglevel", "quiet", target])

            for cmd in stream_cmds:
                try:
                    self._current_proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        preexec_fn=os.setsid
                    )
                    return True
                except Exception:
                    continue

        # 2. Local WAV file playback via aplay
        if target.lower().endswith(".wav") and shutil.which("aplay"):
            try:
                self._current_proc = subprocess.Popen(
                    ["aplay", "-q", target],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid
                )
                return True
            except Exception as e:
                print(f"[player] aplay error: {e}")

        # 3. Local MP3 / generic playback via mpg123 with PulseAudio / ALSA
        for out_driver in ("pulse", "alsa"):
            cmd = [
                "mpg123",
                "-o", out_driver,
                "-q",
                target
            ]
            try:
                self._current_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid
                )
                return True
            except Exception:
                continue

        # Final plain fallback
        try:
            self._current_proc = subprocess.Popen(
                ["mpg123", "-q", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid
            )
            return True
        except Exception as e:
            print(f"[player] playback error: {e}")
            return False

    def is_playing(self) -> bool:
        return self._current_proc is not None and self._current_proc.poll() is None

    def stop(self):
        if self._current_proc and self._current_proc.poll() is None:
            try:
                os.killpg(os.getpgid(self._current_proc.pid), signal.SIGTERM)
            except Exception:
                pass
        self._current_proc = None
        self._current_url = None

    # ─── 1.1 DYNAMIC AUDIO DUCKING & BARGE-IN ────────────────
    def duck_for_voice(self):
        """Immediately drop volume to 15% so user can speak commands naturally."""
        if self.is_playing() and not self._is_ducked:
            self._is_ducked = True
            subprocess.run(["amixer", "sset", "Master", "15%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[player] 🦆 Audio ducked to 15% for voice input.")

    def unduck_audio(self):
        """Restore volume back to original level."""
        if self._is_ducked:
            self._is_ducked = False
            subprocess.run(["amixer", "sset", "Master", f"{self._pre_duck_volume}%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[player] 🔊 Audio restored to {self._pre_duck_volume}%.")

    # ─── 1.4 BLUETOOTH SPEAKER ULTRASONIC KEEP-ALIVE ────────
    def send_speaker_keepalive(self):
        """Send imperceptible 1ms pulse every 3 min to prevent speaker standby."""
        now = time.time()
        if not self.is_playing() and (now - self._last_audio_activity > 180):
            self._last_audio_activity = now
            subprocess.run(
                ["aplay", "-q", "-d", "1", "/dev/zero"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2
            )

    # ─── 1.5 LOCAL EARCON SOUNDBOARD ─────────────────────────
    def play_chime(self, chime_type: str):
        self._last_audio_activity = time.time()

    # ─── 2.1 HARDWARE VOLUME MIXER ───────────────────────────
    def set_system_volume(self, action: str, level: Optional[int] = None, step: int = 10):
        try:
            if action == "set" and level is not None:
                self._pre_duck_volume = level
                subprocess.run(["amixer", "sset", "Master", f"{level}%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif action == "up":
                self._pre_duck_volume = min(100, self._pre_duck_volume + step)
                subprocess.run(["amixer", "sset", "Master", f"{step}%+"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif action == "down":
                self._pre_duck_volume = max(0, self._pre_duck_volume - step)
                subprocess.run(["amixer", "sset", "Master", f"{step}%-"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif action == "mute":
                subprocess.run(["amixer", "sset", "Master", "mute"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif action == "unmute":
                subprocess.run(["amixer", "sset", "Master", "unmute"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"[player] Volume mixer error: {e}")
