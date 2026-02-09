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
    # 2. Stop existing music
    try:
        if current_player and current_player.poll() is None:
            print("[music] Stopping previous track...", flush=True)
            current_player.terminate()
            current_player.wait(timeout=2)
    except Exception:
        pass
        
    # FORCE KILL any lingering mpg123
    try:
        subprocess.run(["pkill", "-9", "mpg123"], stderr=subprocess.DEVNULL)
    except Exception:
        pass
    
    # 1. Clean query
    # Check JSON cache first to skip search
    import json
    from pathlib import Path
    
    cache_dir = Path.home() / "Downloads" / "rk_music_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    index_file = cache_dir / "music_index.json"
    
    music_cache = {}
    if index_file.exists():
        try:
            with open(index_file, "r") as f:
                music_cache = json.load(f)
        except Exception:
            pass
            
    # Normalize query for cache lookup
    clean_q = _clean_query(query).lower().strip()
    vid_id = music_cache.get(clean_q)
    title = None # Initialize title
    
    if vid_id:
        print(f"[music] Found in cache index: '{clean_q}' -> {vid_id}", flush=True)
        title = clean_q # We don't have title from cache, but vid_id is enough
    else:
        # Announce searching
        from .audio_utils import speak
        speak(f"Searching for {clean_q}")
        
        # Search YouTube  
        title, vid_id = _search_youtube(query)
        if not vid_id:
            print("[music] No results found", flush=True)
            return None
            
        # Save to cache index
        music_cache[clean_q] = vid_id
        # Also map title if different
        if title:
             music_cache[title.lower().strip()] = vid_id
             
        try:
            with open(index_file, "w") as f:
                json.dump(music_cache, f)
        except Exception as e:
            print(f"[music] Failed to save cache index: {e}")
    
    # 4. Check cache for MP3 (we want MP3 for mpg123)
    # cache_dir is already defined above
    cache_file = cache_dir / f"{vid_id}.mp3"
    
    if not cache_file.exists():
        # 5. Download MP3 (User specifically requested MPG123 playback)
        from .audio_utils import speak
        speak("Downloading, please wait")
        
        print("[music] Downloading MP3... (may take ~1-2 mins for conversion)", flush=True)
        youtube_url = f"https://www.youtube.com/watch?v={vid_id}"
        
        try:
            subprocess.run(
                [
                    "yt-dlp",
                    "-x", "--audio-format", "mp3",  # Convert to MP3
                    "-o", str(cache_dir / f"{vid_id}.%(ext)s"), # Output template
                    "--extractor-args", "youtube:player_client=android",
                    youtube_url
                ],
                check=True,
                timeout=180  # longer timeout for conversion
            )
            print(f"[music] Download complete!", flush=True)
        except Exception as e:
            print(f"[music] Download failed: {e}", flush=True)
            return None
    else:
        print(f"[music] Playing from cache (instant!)", flush=True)
    
    # 6. Announce (Already handled by download message if needed, but play message is good)
    # from .audio_utils import speak
    # speak(f"Playing {_clean_query(query)}")
    
    # 7. Play with mpg123 (User tested and confirmed working with zero lag)
    print(f"[music] Starting playback with mpg123...", flush=True)
    try:
        # Use mpg123 with minimal flags (as per user successful test)
        # -q: Quiet (suppress banner)
        current_player = subprocess.Popen([
            "mpg123", 
            "-q",
            str(cache_file)
        ])
        
        print(f"[music] Playback started: PID={current_player.pid}", flush=True)
        return current_player
    except Exception as e:
        print(f"[music] Playback failed: {e}", flush=True)
        return None
