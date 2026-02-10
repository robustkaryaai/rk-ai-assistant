"""Music streaming - instant playback with mpg123."""

import subprocess
import shutil
import os
from .audio_utils import speak
import signal

current_player = None


def stop_music():
    """Stop any currently playing music."""
    global current_player
    if current_player:
        current_player.terminate()
        current_player = None
    
    # Force kill
    subprocess.run(["pkill", "-9", "vlc"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "cvlc"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "ffplay"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "mpv"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "mpg123"], stderr=subprocess.DEVNULL)
    
    print("[music] ⏹️  Stopped", flush=True)


def play_music(query: str):
    """
    Stream music directly to mpg123 (works with Bluetooth, instant playback).
    """
    global current_player
    
    # Check dependencies
    if not shutil.which("yt-dlp"):
        print("[music] Install yt-dlp: sudo wget https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -O /usr/local/bin/yt-dlp && sudo chmod a+rx /usr/local/bin/yt-dlp", flush=True)
        return None
    
    stop_music()
    
    print(f"[music] 🔍 Searching: {query}", flush=True)
    speak(f"Searching for {query}")
    
    try:
        # 1. Get Video ID and Title
        # We need the ID to download reliably
        search_cmd = ["yt-dlp", "--force-ipv4", "--get-title", "--get-id", f"ytsearch1:{query}"]
        search_res = subprocess.run(search_cmd, capture_output=True, text=True)
        
        if search_res.returncode != 0:
             print("[music] Error finding song", flush=True)
             print(f"[music] yt-dlp stderr: {search_res.stderr}", flush=True)
             speak("I couldn't find that song.")
             return None
             
        lines = search_res.stdout.strip().split('\n')
        if len(lines) < 2:
            print("[music] ❌ No results or malformed output", flush=True)
            speak("I couldn't find that song.")
            return None
            
        title = lines[0]
        vid_id = lines[1]
        
        print(f"[music] ✓ Found: {title} ({vid_id})", flush=True)
        
        # Cache directory
        cache_dir = os.path.join(os.getcwd(), "songs")
        os.makedirs(cache_dir, exist_ok=True)
        file_path = os.path.join(cache_dir, f"{vid_id}.mp3")
        
        # Check cache
        if os.path.exists(file_path):
            print(f"[music] 📂 Playing from cache: {file_path}", flush=True)
            speak(f"Playing {title}")
        else:
            # Not in cache, download
            speak(f"Downloading the song, please wait.")
            print(f"[music] ⬇️ Downloading...", flush=True)
            
            dl_cmd = [
                "yt-dlp", 
                "--force-ipv4", 
                "-x", "--audio-format", "mp3", 
                "-o", file_path, 
                f"https://www.youtube.com/watch?v={vid_id}"
            ]
            
            dl_res = subprocess.run(dl_cmd, capture_output=True, text=True)
            
            if dl_res.returncode != 0:
                print(f"[music] Download failed: {dl_res.stderr}", flush=True)
                speak("I couldn't download the song. Please make sure ffmpeg is installed.")
                return None
                
            speak(f"Playing {title}")
            print(f"[music] ▶️  Playing new download...", flush=True)

        # User requested mpg123 ONLY
        return subprocess.Popen(
            ["mpg123", "-o", "pulse", "-q", file_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
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
    subprocess.run(["pkill", "-9", "vlc"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "cvlc"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "ffplay"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "mpv"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "mpg123"], stderr=subprocess.DEVNULL)
    
    print("[music] ⏹️  Stopped", flush=True)


def pause_music():
    """Pause music using SIGSTOP (better than ducking)."""
    global current_player
    if current_player and current_player.poll() is None:
        try:
            current_player.send_signal(signal.SIGSTOP)
            print("[music] ⏸️  Paused", flush=True)
        except Exception as e:
            print(f"[music] Pause error: {e}", flush=True)

def unpause_music():
    """Resume music using SIGCONT."""
    global current_player
    if current_player and current_player.poll() is None:
        try:
            current_player.send_signal(signal.SIGCONT)
            print("[music] ▶️  Resumed", flush=True)
        except Exception as e:
            print(f"[music] Resume error: {e}", flush=True)
