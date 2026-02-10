"""Music playback manager with streaming support."""

import subprocess
import shutil

# Global player process
current_player = None


def play_music(query: str):
    """
    Stream music directly using mpv + yt-dlp.
    
    Why streaming:
    - Downloads timeout on slow Pi internet
    - mpv handles buffering automatically
    - Instant playback
    
    Returns:
        subprocess.Popen object or None
    """
    global current_player
    
    # 1. Check dependencies
    if not shutil.which("mpv"):
        print("[music] ERROR: mpv not installed. Run: sudo apt-get install -y mpv", flush=True)
        return None
    
    if not shutil.which("yt-dlp"):
        print("[music] ERROR: yt-dlp not installed. Run: sudo apt-get install -y yt-dlp", flush=True)
        return None
    
    # 2. Stop existing music
    try:
        if current_player and current_player.poll() is None:
            print("[music] Stopping previous track...", flush=True)
            current_player.terminate()
            current_player.wait(timeout=2)
    except Exception:
        pass
        
    # FORCE KILL any lingering players
    try:
        subprocess.run(["pkill", "-9", "mpv"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "mpg123"], stderr=subprocess.DEVNULL)
    except Exception:
        pass
    
    # 3. Search YouTube for the song
    print(f"[music] Searching: {query}", flush=True)
    try:
        search_cmd = [
            "yt-dlp",
            "--force-ipv4",
            f"ytsearch1:{query}",
            "--get-id",
            "--get-title"
        ]
        result = subprocess.run(
            search_cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"[music] Search failed: {result.stderr}", flush=True)
            return None
            
        lines = result.stdout.strip().split('\n')
        if len(lines) < 2:
            print(f"[music] No results found for: {query}", flush=True)
            return None
            
        title = lines[0]
        video_id = lines[1]
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        
        print(f"[music] Found: {title}", flush=True)
        print(f"[music] Streaming: {youtube_url}", flush=True)
        
        # 4. Stream with mpv directly (no download needed!)
        player = subprocess.Popen(
            [
                "mpv",
                "--no-video",           # Audio only
                "--really-quiet",       # Suppress mpv output
                "--audio-device=pulse", # Use PulseAudio
                "--ytdl-format=18",     # 360p MP4 (small, fast)
                "--cache=yes",          # Enable buffering
                "--demuxer-max-bytes=10M",  # 10MB buffer
                youtube_url
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        current_player = player
        print(f"[music] ▶️  Now streaming!", flush=True)
        return player
        
    except subprocess.TimeoutExpired:
        print("[music] Search timed out", flush=True)
        return None
    except Exception as e:
        print(f"[music] Error: {e}", flush=True)
        return None


def stop_music():
    """Stop currently playing music."""
    global current_player
    try:
        if current_player and current_player.poll() is None:
            current_player.terminate()
            current_player.wait(timeout=2)
            print("[music] Stopped", flush=True)
    except Exception:
        pass
    
    # Force kill
    try:
        subprocess.run(["pkill", "-9", "mpv"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-9", "mpg123"], stderr=subprocess.DEVNULL)
    except Exception:
        pass
