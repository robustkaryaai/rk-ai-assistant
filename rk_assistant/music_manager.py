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
    """Search YouTube and return (title, url)."""
    clean_q = _clean_query(query)
    print(f"[music] Searching: {clean_q}", flush=True)
    
    cmd = [
        "yt-dlp",
        f"ytsearch1:{clean_q}",
        "--get-title",
        "--get-url",
        "-f", "bestaudio",
        "--no-playlist"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)
        lines = result.stdout.strip().split('\n')
        
        if len(lines) >= 2:
            title = lines[0]
            url = lines[1]
            print(f"[music] Found: {title}", flush=True)
            return title, url
    except Exception as e:
        print(f"[music] Search error: {e}", flush=True)
    
    return None, None


def play_music(query: str):
    """
    Play music using ffplay (most reliable for audio routing).
    
    ffplay handles PulseAudio/ALSA better than mpg123.
    Plays YouTube stream directly - no download needed.
    
    Returns:
        subprocess.Popen object or None
    """
    # Check dependencies
    if not shutil.which("yt-dlp"):
        print("[music] ERROR: yt-dlp not installed", flush=True)
        return None
    
    if not shutil.which("ffplay"):
        print("[music] ERROR: ffplay not installed. Run: sudo apt-get install ffmpeg", flush=True)
        return None
    
    # 1. Search YouTube
    title, stream_url = _search_youtube(query)
    if not stream_url:
        print("[music] No results found", flush=True)
        return None
    
    # 2. Announce
    from .audio_utils import speak
    speak(f"Playing {_clean_query(query)}")
    
    # 3. Play with ffplay
    # -nodisp: no video display
    # -autoexit: close when done
    # -loglevel quiet: suppress FFmpeg logs
    print("[music] Starting playback with ffplay...", flush=True)
    
    try:
        proc = subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", stream_url],
            stdout=subprocess.DEVNULL
        )
        print(f"[music] Playback started: PID={proc.pid}", flush=True)
        return proc
    except Exception as e:
        print(f"[music] Playback failed: {e}", flush=True)
        return None
