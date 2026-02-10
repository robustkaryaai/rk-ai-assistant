"""Music streaming - instant playback with mpg123."""

import subprocess
import shutil

current_player = None


def play_music(query: str):
    """
    Stream music directly to mpg123 (works with Bluetooth, instant playback).
    """
    global current_player
    
    # Check dependencies
    if not shutil.which("mpg123"):
        print("[music] Install mpg123: sudo apt-get install -y mpg123", flush=True)
        return None
    
    if not shutil.which("yt-dlp"):
        print("[music] Install yt-dlp: sudo apt-get install -y yt-dlp", flush=True)
        return None
    
    # Kill any existing player
    stop_music()
    
    # Search YouTube
    print(f"[music] 🔍 Searching: {query}", flush=True)
    
    try:
        # Get video ID and title
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
        
        # Get DIRECT audio stream URL from yt-dlp
        stream_url_result = subprocess.run(
            [
                "yt-dlp",
                "--force-ipv4",
                "-f", "bestaudio",
                "-g",  # Get direct URL
                url
            ],
            capture_output=True,
            text=True
        )
        
        if stream_url_result.returncode != 0 or not stream_url_result.stdout.strip():
            print("[music] ❌ Failed to get stream URL", flush=True)
            return None
        
        stream_url = stream_url_result.stdout.strip()
        
        # Try ffplay first (fastest streaming, good buffering)
        if shutil.which("ffplay"):
            print(f"[music] 🎵 Streaming with ffplay...", flush=True)
            player = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-hide_banner", "-loglevel", "quiet", stream_url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            current_player = player
            return player
            
        # Fallback to mpv
        elif shutil.which("mpv"):
            print(f"[music] 🎵 Streaming with mpv...", flush=True)
            player = subprocess.Popen(
                ["mpv", "--no-video", "--really-quiet", "--audio-device=pulse", stream_url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            current_player = player
            return player
            
        # Fallback to mpg123 (slow buffering but works)
        else:
            print(f"[music] 🎵 Streaming with mpg123...", flush=True)
            player = subprocess.Popen(
                ["mpg123", "-o", "pulse", "-q", stream_url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            current_player = player
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
    subprocess.run(["pkill", "-9", "ffplay"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "mpv"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "mpg123"], stderr=subprocess.DEVNULL)
    
    print("[music] ⏹️  Stopped", flush=True)
