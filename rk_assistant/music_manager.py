"""
Music Manager for RK AI Assistant
Production-ready YouTube music playback with Bluetooth audio support.
"""
import subprocess
import threading
import shutil
from pathlib import Path

# Music cache directory
MUSIC_CACHE_DIR = Path.home() / "Downloads" / "rk_music_cache"
MUSIC_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _clean_query(query: str) -> str:
    """Remove filler words from music query."""
    fillers = ['play', 'from youtube', 'from yt', 'on youtube', 'song', 'music']
    q = query.lower()
    for f in fillers:
        q = q.replace(f, '')
    return q.strip()


def _search_youtube(query: str):
    """Search YouTube and return (title, url, video_id)."""
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
            url = f"https://www.youtube.com/watch?v={vid_id}"
            print(f"[music] Found: {title}", flush=True)
            return title, url, vid_id
    except subprocess.TimeoutExpired:
        print("[music] Search timeout", flush=True)
    except Exception as e:
        print(f"[music] Search error: {e}", flush=True)
    
    return None, None, None


def _download_background(url: str, vid_id: str):
    """Download MP3 in background thread for caching."""
    def download():
        cache_file = MUSIC_CACHE_DIR / f"{vid_id}.mp3"
        if cache_file.exists():
            print(f"[music] Already cached: {cache_file.name}", flush=True)
            return
        
        print(f"[music] Background download started", flush=True)
        try:
            subprocess.run(
                ["yt-dlp", "-x", "--audio-format", "mp3", "-o", str(cache_file).replace(".mp3", ""), url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=300
            )
            print(f"[music] Download complete: {cache_file.name}", flush=True)
        except Exception as e:
            print(f"[music] Download failed: {e}", flush=True)
    
    threading.Thread(target=download, daemon=True).start()


def play_music(query: str):
    """
    Main music playback function.
    
    Strategy:
    1. Check cache first (instant playback)
    2. If not cached, download synchronously
    3. Play the downloaded file (guaranteed to work with Bluetooth)
    
    Returns:
        subprocess.Popen object or None
    """
    # Check dependencies first
    if not shutil.which("yt-dlp") or not shutil.which("mpg123"):
        print("[music] ERROR: yt-dlp or mpg123 not installed", flush=True)
        return None
    
    # 1. Search YouTube
    title, url, vid_id = _search_youtube(query)
    if not url:
        print("[music] No results found", flush=True)
        return None
    
    # 2. Check cache first
    cache_file = MUSIC_CACHE_DIR / f"{vid_id}.mp3"
    
    if cache_file.exists():
        print(f"[music] Playing from cache: {cache_file.name}", flush=True)
    else:
        # 3. Download first (synchronous)
        print("[music] Downloading...", flush=True)
        try:
            subprocess.run(
                ["yt-dlp", "-x", "--audio-format", "mp3", "-o", str(cache_file).replace(".mp3", ""), url],
                check=True,
                timeout=180,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE
            )
            print(f"[music] Download complete", flush=True)
        except Exception as e:
            print(f"[music] Download failed: {e}", flush=True)
            return None
    
    # 4. Announce
    from .audio_utils import speak
    speak(f"Playing {_clean_query(query)}")
    
    # 5. Play the file (proven to work with Bluetooth!)
    print(f"[music] Playing: {cache_file.name}", flush=True)
    try:
        proc = subprocess.Popen(["mpg123", "-q", str(cache_file)])
        print(f"[music] Playback started: PID={proc.pid}", flush=True)
        return proc
    except Exception as e:
        print(f"[music] Playback failed: {e}", flush=True)
        return None
