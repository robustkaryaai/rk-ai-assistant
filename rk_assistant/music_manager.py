"""Music streaming - instant playback with mpg123."""

import subprocess
import shutil
import os
from .audio_utils import speak

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
        # Get title and URL in one go
        # --get-url returns the direct stream URL if -f is specified, otherwise the video URL.
        # We want the direct stream URL for mpg123/vlc/mpv.
        full_cmd = ["yt-dlp", "--force-ipv4", "-f", "bestaudio", "--get-title", "--get-url", "--default-search", f"ytsearch1:{query}"]
        full_result = subprocess.run(full_cmd, capture_output=True, text=True)
        
        if full_result.returncode != 0:
             print("[music] Error finding song", flush=True)
             speak("I couldn't find that song.")
             return None
             
        lines = full_result.stdout.strip().split('\n')
        
        title = None
        stream_url = None

        if len(lines) >= 2:
            # yt-dlp --get-title --get-url outputs title first, then url
            title = lines[0]
            stream_url = lines[1]
        else:
            print("[music] ❌ No results or malformed output", flush=True)
            speak("I couldn't find that song.")
            return None

        if not title or not stream_url:
            print("[music] Could not extract title or stream URL", flush=True)
            speak("I couldn't find that song.")
            return None
            
        print(f"[music] ✓ Found: {title}", flush=True)
        speak(f"Playing {title}")
        print(f"[music] ▶️  Streaming...", flush=True)

        # Try players in order of quality/reliability
        
        # 1. VLC (cvlc) - Best quality and streaming support
        try:
            print(f"[music] 🎵 Streaming with VLC...", flush=True)
            # --no-video: audio only
            # --play-and-exit: quit when done
            # -q: quiet
            return subprocess.Popen(
                ["cvlc", "--no-video", "--play-and-exit", "-q", stream_url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            pass

        # 2. mpv - Good quality
        try:
            print(f"[music] 🎵 Streaming with mpv...", flush=True)
            return subprocess.Popen(
                ["mpv", "--no-video", "--really-quiet", stream_url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except FileNotFoundError:
            pass

        # 3. mpg123 - Reliable fallback
        # Added --preload 0.1 to try to start faster? No, standard settings usually work if network is good.
        # The --force-ipv4 on yt-dlp should fix the main delay.
        print(f"[music] 🎵 Streaming with mpg123...", flush=True)
        return subprocess.Popen(
            ["mpg123", "-o", "pulse", "-q", stream_url],
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
