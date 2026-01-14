"""
Music Manager for RK Assistant.
Handles searching, streaming, and caching music locally.
"""

import os
import subprocess
import threading
import glob
import shlex
import time
from pathlib import Path

# Directory to store downloaded music
MUSIC_CACHE_DIR = Path.home() / "Downloads" / "rk_music_cache"
MUSIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _get_safe_filename(query):
    """Convert query to safe filename."""
    return "".join(c for c in query if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_').lower()


def _download_in_background(url, output_path):
    """Download audio in background for future offline use."""
    def _download():
        try:
            print(f"[music] Starting background download: {url}", flush=True)
            # yt-dlp download options for best audio
            cmd = [
                "yt-dlp",
                "-x", "--audio-format", "mp3",
                "-o", str(output_path).replace(".mp3", ""), # yt-dlp adds extension
                url,
                "--quiet"
            ]
            subprocess.run(cmd, check=True)
            print(f"[music] Download complete: {output_path}", flush=True)
        except Exception as e:
            print(f"[music] Download failed: {e}", flush=True)

    thread = threading.Thread(target=_download, daemon=True)
    thread.start()


def play_music(query):
    """
    Play music by query.
    1. Check local cache -> Play instant.
    2. Search YouTube -> Stream + Download background.
    
    Returns: subprocess.Popen object of the player.
    """
    safe_name = _get_safe_filename(query)
    # Search for existing file (partial match allowed)
    existing_files = list(MUSIC_CACHE_DIR.glob(f"*{safe_name}*.mp3"))
    
    if existing_files:
        # === CACHE HIT ===
        file_path = existing_files[0]
        print(f"[music] Playing from cache: {file_path}", flush=True)
        return subprocess.Popen(["mpg123", "-q", str(file_path)])
    
    else:
        # === CACHE MISS ===
        print(f"[music] Searching YouTube for: {query}", flush=True)
        try:
            # Get video URL and Title
            # ytsearch1 returns the first result
            cmd_search = [
                "yt-dlp",
                f"ytsearch1:{query}",
                "--get-url",
                "--get-title",
                "--no-playlist",
                "-f", "bestaudio"
            ]
            
            result = subprocess.run(cmd_search, capture_output=True, text=True, check=True)
            output = result.stdout.strip().split('\n')
            
            if len(output) < 1:
                print("[music] No results found.")
                return None
                
            title = output[0]
            url = output[1] if len(output) > 1 else output[0] # Sometimes title isn't returned if --get-url is first? 
            # Actually --get-title --get-url returns Title\nURL
            
            if url.startswith("http"):
                # Correct order check: Title, URL
                pass
            else:
                # Swap if needed (unlikely with this command order but safety check)
                if title.startswith("http"):
                    title, url = url, title
            
            print(f"[music] Found: {title}", flush=True)
            print(f"[music] URL: {url}", flush=True)

            # Start Background Download
            save_path = MUSIC_CACHE_DIR / f"{safe_name}.mp3"
            _download_in_background(url, save_path)
            
            # Stream Immediately
            print("[music] Streaming...", flush=True)
            # mpg123 can play URLs directly, but sometimes fails with complex YouTube URLs.
            # Using yt-dlp -o - | mpg123 - is more robust for streams.
            
            stream_cmd = f"yt-dlp '{url}' -o - -f bestaudio --quiet | mpg123 -q -"
            return subprocess.Popen(stream_cmd, shell=True)
            
        except subprocess.CalledProcessError as e:
            print(f"[music] Search failed: {e}", flush=True)
            return None
        except Exception as e:
            print(f"[music] Error: {e}", flush=True)
            return None
