import os
import re
import shutil
import subprocess
import requests
from pathlib import Path
from typing import Optional, Dict, Any

try:
    from config import BASE_DIR
except ImportError:
    from v2.config import BASE_DIR

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
        target_url = f"ytsearch1:{clean_q}"
        print(f"🎵 [MUSIC-RESOLVE] Target: {target_url}")

        # Method 1: In-process yt_dlp Python API (Fastest & most reliable)
        try:
            from yt_dlp import YoutubeDL
            ydl_opts = {
                "format": "bestaudio/best",
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "socket_timeout": 5,
            }
            if do_download:
                out_tmpl = str(MUSIC_DOWNLOAD_DIR / f"{safe_filename}.%(ext)s")
                ydl_opts["outtmpl"] = out_tmpl
                ydl_opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
                with YoutubeDL(ydl_opts) as ydl:
                    print(f"📥 [MUSIC-DOWNLOAD] In-process downloading '{clean_q}'...")
                    ydl.download([target_url])
                if cached_file.exists() and cached_file.stat().st_size > 10000:
                    return str(cached_file)
            else:
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(target_url, download=False)
                    if info:
                        entries = info.get("entries")
                        first = entries[0] if entries else info
                        stream_url = first.get("url")
                        if stream_url:
                            print("✅ [MUSIC-RESOLVE] In-process live stream URL resolved!")
                            return stream_url
        except Exception as e:
            print(f"[music-resolve] In-process yt_dlp error: {e}")

        # Method 2: CLI subprocess fallback
        if shutil.which("yt-dlp"):
            escaped_q = clean_q.replace('"', '\\"')
            cmd_str = f'yt-dlp -f ba -g --no-playlist --socket-timeout 5 "ytsearch1:{escaped_q}"'
            try:
                res = subprocess.run(cmd_str, shell=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30)
                for line in res.stdout.strip().splitlines():
                    line = line.strip()
                    if line.startswith("http"):
                        print("✅ [MUSIC-RESOLVE] CLI live stream URL resolved!")
                        return line
            except Exception as e:
                print(f"[music-resolve] CLI yt-dlp error: {e}")

        return None
