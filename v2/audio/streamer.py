import subprocess
import shutil
import urllib.parse
import re
from typing import Optional

class LocalMusicStreamer:
    """
    Local YouTube audio resolver using yt-dlp or direct stream extraction.
    Does NOT require the backend to resolve YouTube audio links!
    """

    @staticmethod
    def get_audio_stream_url(query: str) -> Optional[str]:
        """
        Takes a song name (e.g. 'sandese aate hain'),
        finds the YouTube audio stream URL via yt-dlp, and returns direct stream.
        """
        if not query:
            return None

        # Clean query: strip trailing 'on youtube', 'on spotify'
        clean_q = re.sub(r"\b(on youtube|on spotify|from youtube|from spotify)\b", "", query, flags=re.I).strip()
        print(f"🔍 [MUSIC-RESOLVE] Searching locally for: '{clean_q}'...")

        if shutil.which("yt-dlp"):
            # yt-dlp command to get direct streaming audio URL (format bestaudio)
            cmd = [
                "yt-dlp",
                "-f", "bestaudio[ext=m4a]/bestaudio/best",
                "-g", # Get URL only (no download)
                "--quiet",
                "--no-warnings",
                "--force-ipv4",
                f"ytsearch1:{clean_q}"
            ]
            try:
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=12)
                url = res.stdout.strip()
                if url.startswith("http"):
                    print(f"✅ [MUSIC-RESOLVE] Stream resolved successfully.")
                    return url
            except Exception as e:
                print(f"[music-resolve] yt-dlp resolution error: {e}")

        return None
