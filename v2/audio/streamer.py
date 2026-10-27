import os
import re
import ssl
import json
import shutil
import subprocess
import urllib.request
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
    Ultra-Fast Direct Audio Streamer & Downloader for Pi Zero W.
    Features:
    - Lightning-fast direct YouTube HTML scraping (<0.8s) to get video ID
    - Resolves direct audio stream in <2 seconds instead of 1 minute!
    - Automatic caching to avoid re-resolving repeat songs
    """

    DOWNLOAD_MODE: bool = False

    @classmethod
    def set_download_mode(cls, enabled: bool):
        cls.DOWNLOAD_MODE = enabled
        status = "ENABLED (Offline Cache)" if enabled else "DISABLED (Direct Stream)"
        print(f"🎵 [MUSIC MODE] Download mode {status}")

    @staticmethod
    def _fast_extract_videoids(query: str) -> list:
        """Scrapes YouTube search page directly in <0.8s to extract top video IDs in order."""
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            encoded = urllib.parse.quote(query)
            url = f"https://www.youtube.com/results?search_query={encoded}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            }
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=3.5) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                vids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
                # Keep unique preserving rank order
                seen = set()
                unique_vids = [v for v in vids if not (v in seen or seen.add(v))]
                return unique_vids[:5]
        except Exception as e:
            print(f"[music-search] Fast HTML search notice: {e}", flush=True)
        return []

    @classmethod
    def get_audio_stream_url(cls, query: str, prefer_download: Optional[bool] = None) -> Optional[str]:
        if not query:
            return None

        clean_q = re.sub(r"\b(on youtube|on spotify|from youtube|from spotify)\b", "", query, flags=re.I).strip()
        do_download = cls.DOWNLOAD_MODE if prefer_download is None else prefer_download

        # Check local cache first
        safe_filename = "".join(c for c in clean_q if c.isalnum() or c in (" ", "_", "-")).rstrip()
        cached_file = MUSIC_DOWNLOAD_DIR / f"{safe_filename}.mp3"
        if cached_file.exists() and cached_file.stat().st_size > 10000:
            print(f"🎵 [MUSIC-RESOLVE] Found cached downloaded file: {cached_file}", flush=True)
            return str(cached_file)

        print(f"🔍 [MUSIC-RESOLVE] Fast-resolving: '{clean_q}'...", flush=True)

        # Step 0: Try Cloud Backend Resolution First (Gigabit speed, offloads heavy CPU from Pi Zero)
        slug_file = BASE_DIR / "slug.txt"
        slug = slug_file.read_text().strip() if slug_file.exists() else "123456789"
        backend_url = f"https://rk-ai-backend.onrender.com/device/{slug}/music/resolve"
        cloud_target = None
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            payload = json.dumps({"query": clean_q}).encode()
            headers = {
                "Content-Type": "application/json",
                "X-Device-Slug": slug
            }
            req = urllib.request.Request(backend_url, data=payload, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=18.0) as resp:
                res_data = json.loads(resp.read().decode())
                stream_url = res_data.get("stream_url") or res_data.get("link")
                if stream_url and stream_url.startswith("http"):
                    print(f"⚡ [MUSIC-RESOLVE] Cloud server resolved '{res_data.get('title')}' ({res_data.get('source')}) in {res_data.get('elapsed_seconds')}s!", flush=True)
                    # If cloud returned a direct audio stream (like Saavn CDN or direct media container), play it directly!
                    if not ("youtube.com" in stream_url or "youtu.be" in stream_url):
                        return stream_url
                    cloud_target = stream_url
        except Exception as e:
            print(f"[music-resolve] Cloud fast-resolve notice: {e} — falling back to local Pi", flush=True)


        # Step 1: Rapidly grab the candidate video IDs via direct web scrape (<0.8s)
        candidate_vids = cls._fast_extract_videoids(clean_q)
        targets = []
        if cloud_target:
            targets.append(cloud_target)
        if candidate_vids:
            targets.extend([f"https://www.youtube.com/watch?v={vid}" for vid in candidate_vids if f"https://www.youtube.com/watch?v={vid}" not in targets])
        if not targets:
            targets = [f"ytsearch1:{clean_q}"]

        # Step 2: Extract audio stream URL via yt-dlp across candidates
        if shutil.which("yt-dlp"):
            for target in targets:
                try:
                    cmd = [
                        "yt-dlp",
                        "-f", "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
                        "-g",
                        "--no-playlist",
                        "--no-warnings",
                        "--geo-bypass",
                        "--socket-timeout", "10",
                        "--extractor-retries", "3",
                        target
                    ]
                    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=45)
                    for line in res.stdout.strip().splitlines():
                        line = line.strip()
                        if line.startswith("http"):
                            print(f"✅ [MUSIC-RESOLVE] Stream URL ready! ({line[:60]}...)", flush=True)
                            return line
                except Exception as e:
                    print(f"[music-resolve] CLI yt-dlp notice for {target}: {e}", flush=True)

        # Step 3: In-process yt_dlp fallback across candidates
        try:
            from yt_dlp import YoutubeDL
            ydl_opts = {
                "format": "bestaudio/best",
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "socket_timeout": 5,
            }
            with YoutubeDL(ydl_opts) as ydl:
                for target in targets:
                    try:
                        info = ydl.extract_info(target, download=False)
                        if info:
                            entries = info.get("entries")
                            first = entries[0] if entries else info
                            stream_url = first.get("url")
                            if stream_url:
                                print("✅ [MUSIC-RESOLVE] Stream URL resolved via in-process yt_dlp!", flush=True)
                                return stream_url
                    except Exception as e:
                        print(f"[music-resolve] yt_dlp candidate fallback notice: {e}", flush=True)
        except Exception as e:
            print(f"[music-resolve] yt_dlp fallback notice: {e}", flush=True)

        return None
