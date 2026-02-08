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


def _get_safe_filename(query: str) -> str:
    """Convert query to safe filename."""
    return "".join(c for c in query if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_').lower()


def _clean_music_query(query: str) -> str:
    """Clean up music query by removing filler words."""
    # Remove common filler words
    filler_words = ['play', 'from youtube', 'from yt', 'on youtube', 'on yt', 'song', 'music']
    clean = query.lower()
    for filler in filler_words:
        clean = clean.replace(filler, '')
    return clean.strip()


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
    # Clean the query first
    clean_query = _clean_music_query(query)
    safe_name = _get_safe_filename(clean_query)
    # Search for existing file (partial match allowed)
    existing_files = list(MUSIC_CACHE_DIR.glob(f"*{safe_name}*.mp3"))
    
    if existing_files:
        # === CACHE HIT ===
        file_path = existing_files[0]
        print(f"[music] Playing from cache: {file_path}", flush=True)
        return subprocess.Popen(["mpg123", "-q", str(file_path)])
    
    else:
        # === CACHE MISS ===
        print(f"[music] Searching YouTube for: {clean_query}", flush=True)
        try:
            # Get video webpage URL (not the direct stream URL which expires)
            cmd_search = [
                "yt-dlp",
                f"ytsearch1:{clean_query}",
                "--get-title",
                "--get-id",
                "--no-playlist"
            ]
            
            print(f"[music] Running: {' '.join(cmd_search)}", flush=True)
            result = subprocess.run(cmd_search, capture_output=True, text=True, check=True)
            output = result.stdout.strip().split('\n')
            
            print(f"[music] yt-dlp output: {output}", flush=True)
            
            if len(output) < 2:
                print(f"[music] No results found. Output was: {output}", flush=True)
                return None
                
            title = output[0]
            video_id = output[1]
            youtube_url = f"https://www.youtube.com/watch?v={video_id}"
            
            print(f"[music] Found: {title}", flush=True)
            print(f"[music] Video ID: {video_id}", flush=True)
            
            # Announce what we're playing (use cleaned query)\n            from .audio_utils import speak
            speak(f"Playing {clean_query}")

            # Start Background Download using YouTube URL (not direct stream)
            save_path = MUSIC_CACHE_DIR / f"{safe_name}.mp3"
            _download_in_background(youtube_url, save_path)
            
            # Stream Immediately using VLC (more reliable than mpg123 for streaming)
            print("[music] Streaming...", flush=True)
            # cvlc = VLC command-line, --play-and-exit stops after song, -I dummy = no GUI
            stream_cmd = f"yt-dlp '{youtube_url}' -o - -f bestaudio --quiet | cvlc - --play-and-exit -I dummy --aout=pulse 2>&1"
            proc = subprocess.Popen(stream_cmd, shell=True)
            
            # Log stream process info
            print(f"[music] Stream process started: PID={proc.pid}", flush=True)
            return proc
            
        except subprocess.CalledProcessError as e:
            print(f"[music] Search failed with code {e.returncode}", flush=True)
            print(f"[music] stdout: {e.stdout}", flush=True)
            print(f"[music] stderr: {e.stderr}", flush=True)
            return None
        except Exception as e:
            print(f"[music] Error: {e}", flush=True)
            return None
