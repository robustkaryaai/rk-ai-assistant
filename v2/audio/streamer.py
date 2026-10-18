import subprocess
import shutil
import requests
import re
from typing import Optional

class LocalMusicStreamer:
    """
    Direct Audio Streamer for Pi Zero W.
    - Resolves YouTube video ID via fast HTTP scraping (<0.4s).
    - Calls yt-dlp to extract the live audio URL or pipes directly into mpg123.
    """

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
            print(f"[music-search] Fast HTTP search warning: {e}")
        return None

    @classmethod
    def get_audio_stream_url(cls, query: str) -> Optional[str]:
        if not query:
            return None

        clean_q = re.sub(r"\b(on youtube|on spotify|from youtube|from spotify)\b", "", query, flags=re.I).strip()
        print(f"🔍 [MUSIC-RESOLVE] Ultra-fast searching for: '{clean_q}'...")

        vid_id = cls._fast_http_search(clean_q)
        target_url = f"https://www.youtube.com/watch?v={vid_id}" if vid_id else f"ytsearch1:{clean_q}"
        print(f"🎵 [MUSIC-RESOLVE] Target: {target_url}")

        if shutil.which("yt-dlp"):
            # Minimalist extraction flags: skip web-page parsing, grab direct audio link
            cmd = [
                "yt-dlp",
                "-f", "ba/b",
                "-g",
                "--no-check-certificates",
                "--prefer-free-formats",
                "--no-playlist",
                "--force-ipv4",
                "--no-warnings",
                target_url
            ]
            try:
                # 45 second timeout for Pi Zero W single-core CPU
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=45)
                url = res.stdout.strip()
                if url.startswith("http"):
                    print("✅ [MUSIC-RESOLVE] Stream URL extracted successfully!")
                    return url
            except Exception as e:
                print(f"[music-resolve] yt-dlp error: {e}")

        return None
