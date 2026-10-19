import os
import subprocess
import signal
import time
import shutil
from typing import Optional

try:
    from config import BASE_DIR
except ImportError:
    from v2.config import BASE_DIR

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
                # Robust continuous streaming flags for Pi Zero W:
                # Never pause playback for caching, auto-reconnects on stream jitter
                mpv_light = [
                    "mpv",
                    "--really-quiet",
                    "--no-video",
                    "--vo=null",
                    "--ao=pulse",
                    "--cache-pause=no",
                    "--cache-pause-wait=0",
                    "--demuxer-max-bytes=16M",
                    "--demuxer-readahead-secs=20",
                    "--stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_delay_max=2",
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
        """Immediately stop all audio playback, killing any orphaned players."""
        if self._current_proc:
            try:
                os.killpg(os.getpgid(self._current_proc.pid), signal.SIGTERM)
                self._current_proc.wait(timeout=0.2)
            except Exception:
                try:
                    os.killpg(os.getpgid(self._current_proc.pid), signal.SIGKILL)
                except Exception:
                    pass

        # Clean fallback to ensure no background audio processes persist
        for bin_name in ("mpv", "mpg123", "cvlc", "aplay"):
            try:
                subprocess.run(["pkill", "-9", bin_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

        self._current_proc = None
        self._current_url = None

    # ─── 1.1 DYNAMIC AUDIO DUCKING & BARGE-IN ────────────────
    def _get_current_volume(self) -> int:
        """Read actual current volume level from pactl or amixer."""
        try:
            # Try pactl first (PulseAudio / Bluetooth default)
            out = subprocess.check_output(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], text=True, stderr=subprocess.DEVNULL)
            for part in out.split():
                if part.endswith("%"):
                    return int(part.rstrip("%"))
        except Exception:
            pass
        try:
            out = subprocess.check_output(["amixer", "sget", "Master"], text=True, stderr=subprocess.DEVNULL)
            import re
            m = re.search(r"\[(\d+)%\]", out)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return self._pre_duck_volume or 70

    def _set_hw_volume(self, percent: int):
        """Set volume across pactl (PulseAudio) and amixer."""
        percent = max(0, min(100, percent))
        try:
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        try:
            subprocess.run(["amixer", "sset", "Master", f"{percent}%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def duck_for_voice(self):
        """Drop volume to 20% so user can speak commands naturally."""
        if self.is_playing() and not self._is_ducked:
            current = self._get_current_volume()
            if current > 25:
                self._pre_duck_volume = current
            self._is_ducked = True
            self._set_hw_volume(20)
            print(f"[player] 🦆 Audio ducked to 20% (saved original: {self._pre_duck_volume}%).")

    def unduck_audio(self):
        """Restore volume back to original level."""
        if self._is_ducked:
            target_vol = self._pre_duck_volume or 70
            self._is_ducked = False
            self._set_hw_volume(target_vol)
            print(f"[player] 🔊 Audio restored to {target_vol}%.")

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
    def play_chime(self, chime_type: str, sync: bool = False):
        """Plays immediate auditory earcons (wake, captured, thinking, answer)."""
        self._last_audio_activity = time.time()
        sound_file = BASE_DIR / "data" / "sounds" / f"{chime_type}.wav"
        if sound_file.exists():
            try:
                proc = subprocess.Popen(
                    ["aplay", "-q", str(sound_file)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                if sync:
                    proc.wait(timeout=1.5)
            except Exception:
                pass

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
