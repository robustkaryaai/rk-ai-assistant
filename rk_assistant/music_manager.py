"""
Music Manager for RK AI Assistant
Production-grade YouTube music playback with proper process management.
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
        # Use regex with word boundaries to replace only whole words
        q = re.sub(rf'\b{re.escape(f)}\b', '', q, flags=re.IGNORECASE)
    return q.strip()


def _search_youtube(query: str):
    """Search YouTube and return (title, video_id) with predictable output format."""
    clean_q = _clean_query(query)
    print(f"[music] Searching: {clean_q}", flush=True)
    
    # Use --print to ensure predictable, one-line-per-field output
    cmd = [
        "yt-dlp",
        f"ytsearch1:{clean_q}",
        "--print", "%(title)s",
        "--print", "%(id)s",
        "--no-playlist"
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
    Play music using mpv with YouTube URL.
    
    Features:
    - Stops previous track automatically (no zombie processes)
    - Uses mpv's internal yt-dlp integration (bypasses 403 errors)
    - Optimized for audio-only streaming
    
    Returns:
        subprocess.Popen object or None
    """
    global current_player
    
    # 1. Check dependencies FIRST (before any other operations)
    for dep in ["yt-dlp", "mpv"]:
        if not shutil.which(dep):
            print(f"[music] ERROR: {dep} not installed. Run: sudo apt-get install {dep}", flush=True)
            return None
    
    # 2. Stop existing music to prevent overlapping playback
    if current_player and current_player.poll() is None:
        print("[music] Stopping previous track...", flush=True)
        current_player.terminate()
        current_player.wait()
    
    # 3. Search YouTube  
    title, vid_id = _search_youtube(query)
    if not vid_id:
        print("[music] No results found", flush=True)
        return None
    
    # 4. Build YouTube watch URL
    youtube_url = f"https://www.youtube.com/watch?v={vid_id}"
    
    # 5. Announce (NOTE: If speak() is blocking, this will delay playback)
    from .audio_utils import speak
    speak(f"Playing {_clean_query(query)}")
    
    # 6. Play with mpv (uses internal yt-dlp integration)
    # --no-video: audio only
    # --ytdl-format=bestaudio: faster loading on slow connections
    print("[music] Starting playback with mpv...", flush=True)
    
    try:
        current_player = subprocess.Popen(
            ["mpv", "--no-video", "--ytdl-format=bestaudio", youtube_url]
        )
        print(f"[music] Playback started: PID={current_player.pid}", flush=True)
        return current_player
    except Exception as e:
        print(f"[music] Playback failed: {e}", flush=True)
        return None
