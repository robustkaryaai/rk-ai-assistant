"""
Music Manager for RK AI Assistant
Simple and reliable YouTube music playback using ffplay.
"""
import subprocess
import shutil

def _clean_query(query: str) -> str:
    """Remove filler words from music query."""
    fillers = ['play', 'from youtube', 'from yt', 'on youtube', 'song', 'music']
    q = query.lower()
    for f in fillers:
        q = q.replace(f, '')
    return q.strip()


def _search_youtube(query: str):
    """Search YouTube and return (title, video_id)."""
    clean_q = _clean_query(query)
    print(f"[music] Searching: {clean_q}", flush=True)
    
    cmd = [
        "yt-dlp",
        f"ytsearch1:{clean_q}",
        "--get-title",
        "--get-id",
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
    
    mpv has built-in yt-dlp integration that bypasses YouTube's 403 errors.
    We pass the YouTube watch URL directly (not extracted stream URL).
    
    Returns:
        subprocess.Popen object or None
    """
    # Check dependencies
    if not shutil.which("yt-dlp"):
        print("[music] ERROR: yt-dlp not installed", flush=True)
        return None
    
    if not shutil.which("mpv"):
        print("[music] ERROR: mpv not installed. Run: sudo apt-get install mpv", flush=True)
        return None
    
    # 1. Search YouTube  
    title, vid_id = _search_youtube(query)
    if not vid_id:
        print("[music] No results found", flush=True)
        return None
    
    # 2. Build YouTube watch URL
    youtube_url = f"https://www.youtube.com/watch?v={vid_id}"
    
    # 3. Announce
    from .audio_utils import speak
    speak(f"Playing {_clean_query(query)}")
    
    # 4. Play with mpv (uses internal yt-dlp integration)
    # --no-video: audio only
    # --really-quiet: suppress most output but show errors
    print("[music] Starting playback with mpv...", flush=True)
    
    try:
        proc = subprocess.Popen(
            ["mpv", "--no-video", "--really-quiet", youtube_url]
        )
        print(f"[music] Playback started: PID={proc.pid}", flush=True)
        return proc
    except Exception as e:
        print(f"[music] Playback failed: {e}", flush=True)
        return None
