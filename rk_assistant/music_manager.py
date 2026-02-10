"""Music streaming - instant playback with mpg123."""

import subprocess
import shutil
import os
import json
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
    
    # --- 1. Check Local JSON Index (Instant Playback) ---
    cache_dir = os.path.join(os.getcwd(), "songs")
    index_path = os.path.join(cache_dir, "index.json")
    os.makedirs(cache_dir, exist_ok=True)
    
    index = {}
    if os.path.exists(index_path):
        try:
            with open(index_path, "r") as f:
                index = json.load(f)
        except Exception as e:
            print(f"[music] Error loading index: {e}", flush=True)

    # Fuzzy match query against titles or stored queries
    best_match = None
    best_score = 0.0
    
    # Simple normalization
    norm_query = query.lower().strip()
    
    for vid_id, data in index.items():
        # Check against title
        title = data.get("title", "").lower()
        if not title: continue
        
        # Check exact previous queries
        previous_queries = data.get("queries", [])
        if norm_query in previous_queries:
             best_match = vid_id
             best_score = 1.0 # Perfect match
             break
             
        # Fuzzy title match
        from difflib import SequenceMatcher
        score = SequenceMatcher(None, norm_query, title).ratio()
        
        # Also check if query is substring of title or vice versa
        if norm_query in title or title in norm_query:
            if score < 0.7: score = 0.7
            
        if score > best_score:
            best_score = score
            best_match = vid_id
            
    # Threshold for fuzzy match
    if best_score > 0.6 and best_match:
        data = index[best_match]
        file_path = os.path.join(cache_dir, f"{best_match}.mp3")
        if os.path.exists(file_path):
            print(f"[music] ⚡ Instant Hit: {data['title']} (Score: {best_score:.2f})", flush=True)
            speak(f"Playing {data['title']}")
            
            # Update queries list if new
            if norm_query not in data.get("queries", []):
                data.setdefault("queries", []).append(norm_query)
                with open(index_path, "w") as f:
                    json.dump(index, f, indent=2)

            return subprocess.Popen(
                ["mpg123", "-o", "pulse", "-q", file_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
    # --- 2. Not found locally, proceed to Network Search ---
    
    try:
        # Get Video ID and Title
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
        
        file_path = os.path.join(cache_dir, f"{vid_id}.mp3")
        
        # Check if file exists (maybe from old cache without index)
        if os.path.exists(file_path):
            print(f"[music] 📂 Playing from file cache (re-indexing): {file_path}", flush=True)
            # Add to index
            index[vid_id] = {
                "title": title,
                "queries": [norm_query]
            }
            with open(index_path, "w") as f:
                json.dump(index, f, indent=2)
                
            speak(f"Playing {title}")
        else:
            # Download
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
                speak("I couldn't download the song.")
                return None
                
            # Add to index
            index[vid_id] = {
                "title": title,
                "queries": [norm_query]
            }
            with open(index_path, "w") as f:
                json.dump(index, f, indent=2)
                
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
