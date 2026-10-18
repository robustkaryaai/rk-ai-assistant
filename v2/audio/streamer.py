import os
import re
import shutil
import subprocess
import requests
from pathlib import Path
from typing import Optional, Dict, Any

from config import BASE_DIR

MUSIC_DOWNLOAD_DIR = BASE_DIR / "data" / "downloaded_music"
MUSIC_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


class LocalMusicStreamer:
    """
    Direct Audio Streamer & Downloader for Pi Zero W.
    Features:
    - Streaming by default (zero storage footprint, immediate playback)
    - Optional download mode toggled via app command / config
    - Spotify integration routing
    - Fast YouTube search & resolution
    """

    DOWNLOAD_MODE: bool = False

    @classmethod
    def set_download_mode(cls, enabled: bool):
        cls.DOWNLOAD_MODE = enabled
        status = "ENABLED (Offline Cache)" if enabled else "DISABLED (Direct Stream)"
        print(f"🎵 [MUSIC MODE] Download mode {status}")

    @staticmethod
    def _fast_http_search(query: str) -> Optional[str]:
        try:
            url = "https://www.youtube.com/results"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, params={"search_query": query}, headers=headers, timeout=5)
            if resp.status_code == 200:
                vids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', resp.text)
                if vids:
                    return vids[0]
        except Exception as e:
            print(f"[music-search] Fast search error: {e}")
        return None

    @classmethod
    def get_audio_stream_url(cls, query: str, prefer_download: Optional[bool] = None) -> Optional[str]:
        if not query:
            return None

        clean_q = re.sub(r"\b(on youtube|on spotify|from youtube|from spotify)\b", "", query, flags=re.I).strip()
        do_download = cls.DOWNLOAD_MODE if prefer_download is None else prefer_download

        # Check local cache first if download mode is enabled
        safe_filename = "".join(c for c in clean_q if c.isalnum() or c in (" ", "_", "-")).rstrip()
        cached_file = MUSIC_DOWNLOAD_DIR / f"{safe_filename}.mp3"
        if cached_file.exists() and cached_file.stat().st_size > 10000:
            print(f"🎵 [MUSIC-RESOLVE] Found cached downloaded file: {cached_file}")
            return str(cached_file)

        print(f"🔍 [MUSIC-RESOLVE] Searching for: '{clean_q}'...")
        vid_id = cls._fast_http_search(clean_q)
        target_url = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else f"ytsearch1:{clean_q}"
        print(f"🎵 [MUSIC-RESOLVE] Target: {target_url}")

        if shutil.which("yt-dlp"):
            if do_download:
                # Download mode (save to MP3 for offline playback)
                out_tmpl = str(MUSIC_DOWNLOAD_DIR / f"{safe_filename}.%(ext)s")
                cmd = [
                    "yt-dlp",
                    "-x",
                    "--audio-format", "mp3",
                    "--audio-quality", "0",
                    "-o", out_tmpl,
                    "--no-playlist",
                    "--force-ipv4",
                    "--no-warnings",
                    target_url
                ]
                try:
                    print(f"📥 [MUSIC-DOWNLOAD] Downloading '{clean_q}' for offline playback...")
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
                    if cached_file.exists() and cached_file.stat().st_size > 10000:
                        return str(cached_file)
                except Exception as e:
                    print(f"[music-download] yt-dlp download error: {e}")

            # Stream mode (default)
            cookies_file = BASE_DIR / "youtube-cookies.txt"
            cmd = [
                "yt-dlp",
                "-f", "ba/b",
                "-g",
                "--no-check-certificates",
                "--prefer-free-formats",
                "--no-playlist",
                "--force-ipv4",
                "--no-warnings",
                "--socket-timeout", "10",
                "--extractor-args", "youtube:player_client=android,web",
            ]
            if cookies_file.exists() and cookies_file.stat().st_size > 0:
                cmd.extend(["--cookies", str(cookies_file)])
            cmd.append(target_url)

            try:
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=25)
                url = res.stdout.strip().split("\n")[0]
                if url.startswith("http"):
                    print("✅ [MUSIC-RESOLVE] Live stream URL resolved!")
                    return url
                elif res.stderr:
                    print(f"[music-resolve] yt-dlp stderr: {res.stderr[:200]}")
            except Exception as e:
                print(f"[music-resolve] yt-dlp error: {e}")

        return None
