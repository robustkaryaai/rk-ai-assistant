"""Dead-simple music streaming with mpv."""

import subprocess
import shutil

current_player = None


def play_music(query: str):
    """
    Stream music from YouTube using mpv.
    Ultra simple - just search and stream.
    """
    global current_player
    
    # Check mpv
    if not shutil.which("mpv"):
        print("[music] Install mpv: sudo apt-get install -y mpv", flush=True)
        return None
    
    # Kill any existing player
    stop_music()
    
    # Search YouTube
    print(f"[music] 🔍 Searching: {query}", flush=True)
    
    try:
        # Get video URL directly
        search = subprocess.run(
            ["yt-dlp", "--force-ipv4", f"ytsearch1:{query}", "--get-id", "--get-title"],
            capture_output=True,
            text=True
        )
        
        if search.returncode != 0 or not search.stdout.strip():
            print("[music] ❌ Search failed", flush=True)
            return None
        
        lines = search.stdout.strip().split('\n')
        if len(lines) < 2:
            print("[music] ❌ No results", flush=True)
            return None
        
        title = lines[0]
        video_id = lines[1]
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        print(f"[music] ✓ Found: {title}", flush=True)
        print(f"[music] ▶️  Streaming...", flush=True)
        
        # Stream with mpv
        player = subprocess.Popen(
            [
                "mpv",
                "--no-video",
                "--really-quiet",
                "--audio-device=pulse",
                "--ytdl-format=bestaudio/best",
                "--cache=yes",
                "--demuxer-max-bytes=5M",
                url
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        current_player = player
        print("[music] 🎵 Playing!", flush=True)
        return player
        
    except Exception as e:
        print(f"[music] ❌ Error: {e}", flush=True)
        return None


def stop_music():
    """Stop music."""
    global current_player
    
    try:
        if current_player and current_player.poll() is None:
            current_player.terminate()
            current_player.wait(timeout=2)
    except:
        pass
    
    # Force kill
    subprocess.run(["pkill", "-9", "mpv"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "mpg123"], stderr=subprocess.DEVNULL)
    
    print("[music] ⏹️  Stopped", flush=True)
