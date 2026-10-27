import os
import subprocess
import signal
import time
import shutil
import json
from pathlib import Path
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
    - Persists volume level to disk so volume is remembered across reboots
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self._current_proc: Optional[subprocess.Popen] = None
        self._current_url: Optional[str] = None
        self._next_prebuffered_url: Optional[str] = None
        self._is_ducked: bool = False
        self._is_speech: bool = False
        self._is_emergency: bool = False
        self._data_dir = data_dir or (BASE_DIR / "data")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._vol_file = self._data_dir / "volume.json"
        self._pre_duck_volume: int = self._load_saved_volume()
        self._last_audio_activity: float = time.time()
        
        # Apply initial saved volume on startup
        self._set_hw_volume(self._pre_duck_volume)

    def _load_saved_volume(self) -> int:
        if self._vol_file.exists():
            try:
                data = json.loads(self._vol_file.read_text())
                vol = int(data.get("volume", 70))
                return max(0, min(100, vol))
            except Exception:
                pass
        return 70

    def _save_volume(self, vol: int):
        try:
            self._vol_file.write_text(json.dumps({"volume": vol}))
        except Exception:
            pass

    def play_url_or_file(self, target: str, is_speech: bool = False, sync: bool = False) -> bool:
        """Play stream URL or local audio file via mpg123 or aplay."""
        self.stop()
        if not target:
            return False

        self._current_url = target
        self._is_speech = is_speech
        self._last_audio_activity = time.time()

        is_url = target.startswith(("http://", "https://"))

        # 1. Web stream playback (ffplay is highest priority for Pi Zero: zero stutter, light CPU, hardware buffer)
        if is_url:
            for player in ["ffplay", "mpv", "cvlc"]:
                if shutil.which(player):
                    try:
                        if player == "ffplay":
                            args = [
                                "ffplay",
                                "-nodisp",
                                "-autoexit",
                                "-loglevel", "quiet",
                                "-rtbufsize", "10M",
                                target
                            ]
                        elif player == "mpv":
                            args = [
                                "mpv",
                                "--no-video",
                                "--volume=100",
                                "--ytdl=no",
                                "--ao=pulse,alsa",
                                "--audio-samplerate=44100",
                                "--audio-format=s16",
                                "--audio-buffer=1.0",
                                "--cache=yes",
                                "--cache-secs=30",
                                "--really-quiet",
                                target
                            ]
                        elif player == "cvlc":
                            args = ["cvlc", "--play-and-exit", "--no-video", "--quiet", target]

                        self._current_proc = subprocess.Popen(
                            args,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        if sync:
                            self._current_proc.wait()
                        return True
                    except Exception as e:
                        print(f"[player] Error launching {player}: {e}")

        # 2. Local audio files (WAV via aplay, MP3 via mpg123)
        if target.endswith(".wav") and shutil.which("aplay"):
            try:
                self._current_proc = subprocess.Popen(
                    ["aplay", "-q", target],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                if sync:
                    self._current_proc.wait()
                return True
            except Exception as e:
                print(f"[player] aplay error: {e}")

        if target.endswith(".mp3") and shutil.which("mpg123"):
            try:
                self._current_proc = subprocess.Popen(
                    ["mpg123", "-o", "pulse", "-b", "32768", "--no-resync", "-q", target],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                if sync:
                    self._current_proc.wait()
                return True
            except Exception as e:
                print(f"[player] mpg123 error: {e}")
            except Exception as e:
                print(f"[player] aplay error: {e}")

        # 3. Default fallback: mpg123 for MP3 files
        if shutil.which("mpg123"):
            try:
                self._current_proc = subprocess.Popen(
                    ["mpg123", "-q", "-o", "pulse", "-b", "4096", "--no-resync", target],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                if sync:
                    self._current_proc.wait()
                return True
            except Exception as e:
                print(f"[player] mpg123 error: {e}")

        return False

    def play_chime(self, chime_name: str, sync: bool = False):
        chime_file = BASE_DIR / "data" / "sounds" / f"{chime_name}.wav"
        if chime_file.exists():
            self.play_url_or_file(str(chime_file), is_speech=True, sync=sync)

    def start_processing_loop(self):
        """No-op on Pi Zero to save 100% CPU for yt-dlp resolution."""
        pass

    def stop_processing_loop(self, play_finished: bool = False):
        """No-op on Pi Zero to save 100% CPU for yt-dlp resolution."""
        pass

    def is_playing(self) -> bool:
        if self._current_proc is not None:
            if self._current_proc.poll() is None:
                return True
            self._current_proc = None
        return False

    def wait_playback(self, timeout: float = 15.0):
        """Block until current audio finishes playing or timeout expires."""
        if self._current_proc is not None:
            try:
                self._current_proc.wait(timeout=timeout)
            except Exception:
                pass

    def stop(self):
        if self._current_proc is not None:
            try:
                self._current_proc.terminate()
                self._current_proc.wait(timeout=1.0)
            except Exception:
                try:
                    self._current_proc.kill()
                except Exception:
                    pass
            self._current_proc = None
        self._current_url = None
        self._is_speech = False

    def _get_current_volume(self) -> int:
        return self._pre_duck_volume or 70

    def _set_hw_volume(self, percent: int):
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
        if self._is_speech or self._is_emergency:
            return
        if self.is_playing() and not self._is_ducked:
            self._is_ducked = True
            self._set_hw_volume(20)

    def unduck_audio(self):
        """Restore volume back to original level."""
        if self._is_ducked:
            self._is_ducked = False
            self._set_hw_volume(self._pre_duck_volume)

    def unduck_after_voice(self):
        self.unduck_audio()

    def send_speaker_keepalive(self):
        """Keepalive is handled by PulseAudio sink suspension flags."""
        pass

    def set_system_volume(self, action: str, level: Optional[int] = None, step: int = 10, play_chime: bool = True):
        try:
            if action == "set" and level is not None:
                self._pre_duck_volume = max(0, min(100, level))
            elif action == "up":
                self._pre_duck_volume = min(100, self._pre_duck_volume + step)
            elif action == "down":
                self._pre_duck_volume = max(0, self._pre_duck_volume - step)
            elif action == "mute":
                self._set_hw_volume(0)
                return
            elif action == "unmute":
                self._set_hw_volume(self._pre_duck_volume)
                return

            self._set_hw_volume(self._pre_duck_volume)
            self._save_volume(self._pre_duck_volume)
            print(f"🔊 [player] Volume set and saved to {self._pre_duck_volume}%", flush=True)
        except Exception as e:
            print(f"[player] Volume error: {e}", flush=True)

        # Only play volume tick earcon if we aren't currently streaming music or if explicitly requested
        if play_chime and action in ("set", "up", "down"):
            if not self.is_playing():
                self.play_chime("volume_tick")
