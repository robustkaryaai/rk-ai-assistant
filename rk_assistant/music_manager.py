"""Music streaming - using mpg123 for reliable Bluetooth playback."""

import subprocess
import shutil
import tempfile
import os

current_player = None


def play_music(query: str):
    """
    Download audio and play with mpg123 (proven to work with Bluetooth).
    mpv doesn't reliably output to Bluetooth on Pi.
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
        # Get video URL
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
        print(f"[music] 📥 Downloading audio...", flush=True)
        
        # Download to temp file (small, fast)
        temp_file = f"/tmp/rk_music_{video_id}.mp3"
        
        # Quick download with yt-dlp (best audio, fast)
        dl = subprocess.run(
            [
                "yt-dlp",
                "--force-ipv4",
                "-x", "--audio-format", "mp3",
                "--audio-quality", "5",  # Medium quality for speed
                "-o", temp_file,
                "--no-part",
                url
            ],
            capture_output=True,
            timeout=120  # 2 min max
        )
        
        if dl.returncode != 0 or not os.path.exists(temp_file):
            print(f"[music] ❌ Download failed", flush=True)
            return None
        
        print(f"[music] ▶️  Playing...", flush=True)
        
        # Play with mpg123 (works with Bluetooth!)
        player = subprocess.Popen(
            ["mpg123", "-o", "pulse", "-q", temp_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        current_player = player
        print("[music] 🎵 Now playing!", flush=True)
        return player
        
    except subprocess.TimeoutExpired:
        print("[music] ❌ Download timed out", flush=True)
        return None
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
    subprocess.run(["pkill", "-9", "mpg123"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "mpv"], stderr=subprocess.DEVNULL)
    
    # Cleanup temp files
    subprocess.run(["rm", "-f", "/tmp/rk_music_*.mp3"], stderr=subprocess.DEVNULL)
    
    print("[music] ⏹️  Stopped", flush=True)
