"""
Music Manager for RK AI Assistant
Bypasses YouTube 403 errors using Android client extraction.
"""
import subprocess
import shutil
import re

# Global variable to track the current player process
current_player = None


def _clean_query(query: str) -> str:
    """Remove filler words using word boundaries to avoid breaking real words."""
    fillers = ['play', 'from youtube', 'from yt', 'on youtube', 'song', 'music']
    q = query.lower()
    for f in fillers:
        q = re.sub(rf'\b{re.escape(f)}\b', '', q, flags=re.IGNORECASE)
    return q.strip()


def _search_youtube(query: str):
    """Search YouTube and return (title, video_id) bypassing 403 errors."""
    clean_q = _clean_query(query)
    print(f"[music] Searching: {clean_q}", flush=True)
    
    # Use Android client to bypass YouTube blocking
    cmd = [
        "yt-dlp",
        f"ytsearch1:{clean_q}",
        "--print", "%(title)s",
        "--print", "%(id)s",
        "--no-playlist",
        "--extractor-args", "youtube:player_client=android"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)
        lines = result.stdout.strip().split('\n')
        
        if len(lines) >= 2:
            title = lines[0]
            vid_id = lines[1]
            print(f"[music] Found: {title}", flush=True)
            return title, vid_id
    except Exception as e:
        print(f"[music] Search error: {e}", flush=True)
    
    return None, None


def play_music(query: str):
    """
    Play music by downloading completely first, then playing with mpg123.
    
    Why download-first:
    - Streaming always hits 403 errors from YouTube
    - mpg123 file playback is proven to work (via gTTS)
    - Builds offline cache for instant replay
    
    Returns:
        subprocess.Popen object or None
    """
    global current_player
    
    # 1. Check dependencies
    for dep in ["yt-dlp", "mpg123"]:
        if not shutil.which(dep):
            print(f"[music] ERROR: {dep} not installed. Run: sudo apt-get install {dep}", flush=True)
            return None
    
    # 2. Stop existing music
    if current_player and current_player.poll() is None:
        print("[music] Stopping previous track...", flush=True)
        current_player.terminate()
        current_player.wait()
    
    # 3. Search YouTube  
    title, vid_id = _search_youtube(query)
    if not vid_id:
        print("[music] No results found", flush=True)
        return None
    
    # 4. Check cache
    from pathlib import Path
    cache_dir = Path.home() / "Downloads" / "rk_music_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Check for webm or mp3 (backward compatibility)
    cache_file = cache_dir / f"{vid_id}.webm"
    cache_file_mp3 = cache_dir / f"{vid_id}.mp3"
    
    if cache_file_mp3.exists() and not cache_file.exists():
        # Use existing MP3 if we have it
        cache_file = cache_file_mp3
        print(f"[music] Using existing MP3 from cache", flush=True)
    
    if not cache_file.exists():
        # 5. Download video file (no MP3 conversion = much faster on Pi!)
        from .audio_utils import speak
        speak("Downloading, please wait")
        
        print("[music] Downloading... (~20-30s)", flush=True)
        youtube_url = f"https://www.youtube.com/watch?v={vid_id}"
        
        try:
            subprocess.run(
                [
                    "yt-dlp",
                    "-f", "bestaudio",  # Best audio format (usually webm)
                    "-o", str(cache_file).replace(".webm", ""),
                    "--extractor-args", "youtube:player_client=android",
                    youtube_url
                ],
                check=True,
                timeout=120  # Increased to 120s for slow connections
            )
            print(f"[music] Download complete!", flush=True)
        except Exception as e:
            print(f"[music] Download failed: {e}", flush=True)
            return None
    else:
        print(f"[music] Playing from cache (instant!)", flush=True)
    
    # 6. Announce
    from .audio_utils import speak
    speak(f"Playing {_clean_query(query)}")
    
    # 7. Play with mpv (handles audio-only webm perfectly!)
    # Use nice -n -10 for higher CPU priority (reduces crackling)
    # --audio-buffer=1 for 1 second buffer (smooth Bluetooth playback)
    # --volume=80 to prevent clipping/distortion
    # --af=loudnorm to normalize audio levels
    print(f"[music] Starting playback...", flush=True)
    try:
        current_player = subprocess.Popen([
            "nice", "-n", "-10",  # Higher CPU priority
            "mpv", 
            "--no-video",
            "--audio-buffer=1",  # 1 second audio buffer
            "--volume=80",  # Reduce volume to prevent distortion
            "--af=loudnorm",  # Normalize audio levels
            str(cache_file)
        ])
        print(f"[music] Playback started: PID={current_player.pid}", flush=True)
        return current_player
    except Exception as e:
        print(f"[music] Playback failed: {e}", flush=True)
        return None
