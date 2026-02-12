"""Music streaming - instant playback with mpg123."""

import subprocess
import shutil
import os
import json
from .audio_utils import speak
import signal

current_player = None
last_played_query = None


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
        # Basic ratio
        score1 = SequenceMatcher(None, norm_query, title).ratio()
        
        # Keyword match (Custom logic similar to token_set_ratio)
        q_words = set(norm_query.split())
        t_words = set(title.split())
        intersection = q_words.intersection(t_words)
        
        # If significant overlap
        score2 = 0.0
        if q_words:
             score2 = len(intersection) / len(q_words)
             
        score = max(score1, score2)

        # Boost if query is substring
        if norm_query in title or title in norm_query:
            if score < 0.8: score = 0.8
            
        if score > best_score:
            best_score = score
            best_match = vid_id
            
    # Threshold for fuzzy match
    if best_score > 0.6 and best_match:
        data = index[best_match]
        
        # Search for file with this ID (glob because filename might have title)
        # We expect "... [{best_match}].mp3" OR "{best_match}.mp3"
        # Since [ ] might be stripped?
        # Let's search for *{best_match}*
        
        found_file = None
        # Try exact ID.mp3
        possible = cache_dir / f"{best_match}.mp3"
        if possible.exists():
             found_file = str(possible)
        else:
             # Glob search
             matches = list(cache_dir.glob(f"*{best_match}*.mp3"))
             if matches:
                 found_file = str(matches[0])
        
        if found_file:
            print(f"[music] ⚡ Instant Hit: {data['title']} (Score: {best_score:.2f})", flush=True)
            print(f"[music] File: {found_file}", flush=True)
            
            # Shorten title for speaking
            speak_title = data['title']
            if "|" in speak_title:
                speak_title = speak_title.split("|")[0]
            words = speak_title.split()
            if len(words) > 5:
                speak_title = " ".join(words[:5])
                
            speak(f"Playing {speak_title}")
            
            # Update queries list if new
            if norm_query not in data.get("queries", []):
                data.setdefault("queries", []).append(norm_query)
                with open(index_path, "w") as f:
                    json.dump(index, f, indent=2)

            return subprocess.Popen(
                ["mpg123", "-o", "pulse", "-q", found_file],
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
        
        # Sanitize title for filename
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        filename = f"{safe_title} [{vid_id}].mp3"[:255] # safe length
        file_path = str(cache_dir / filename)
        
        print(f"[music] ✓ Found: {title} ({vid_id})", flush=True)
        print(f"[music] Target File: {file_path}", flush=True) # Debug
        
        # Check if file exists (Old format ID.mp3 fallback?)
        old_path = str(cache_dir / f"{vid_id}.mp3")
        if os.path.exists(old_path):
            print(f"[music] 📂 Found old cache format, renaming...", flush=True)
            try:
                os.rename(old_path, file_path)
            except:
                pass

        if os.path.exists(file_path):
            print(f"[music] 📂 Playing from file cache: {file_path}", flush=True)
            # Add to index if missing
            current_data = index.get(vid_id, {})
            index[vid_id] = {"title": title, "queries": [norm_query] + current_data.get("queries", [])}
            with open(index_path, "w") as f:
                json.dump(index, f, indent=2)
                
            # Shorten title   
            speak_title = title
            if "|" in speak_title:
                speak_title = speak_title.split("|")[0]
            words = speak_title.split()
            if len(words) > 5:
                speak_title = " ".join(words[:5])
            speak(f"Playing {speak_title}")
            
            return subprocess.Popen(
                ["mpg123", "-o", "pulse", "-q", file_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        
        # --- Not in Cache: Stream & Save (Pipeline) ---
        
        # Self-healing check: Try to update yt-dlp if it looks broken
        def update_ytdlp():
            print("[music] 🔄 Updating yt-dlp...", flush=True)
            speak("Updating music components...")
            subprocess.run(["sudo", "pip3", "install", "-U", "yt-dlp", "--break-system-packages"], capture_output=True)
            
        speak(f"Playing {title}")
        print(f"[music] ▶️  Streaming & Caching... ({title})", flush=True)
        
        # Pipeline: yt-dlp stdout -> tee file -> mpg123 stdin
        # using shell=True for pipeline simplicity given the complexity of wiring 3 processes
        # Escape quotes for shell
        safe_url = f"https://www.youtube.com/watch?v={vid_id}"
        safe_path = file_path.replace("'", "'\\''")
        
        # CMD: yt-dlp -o - [URL] 2>error.log | tee [FILE] | mpg123 -o pulse -q -
        # We capture stderr to a temp file to check for errors? Or just let it print?
        # User wants speed.
        
        pipeline_cmd = f"yt-dlp --force-ipv4 -x --audio-format mp3 -o - '{safe_url}' | tee '{safe_path}' | mpg123 -o pulse -q -"
        
        # We need to detect if yt-dlp fails.
        # If the pipe breaks immediately.
        
        proc = subprocess.Popen(pipeline_cmd, shell=True)
        
        # Wait a bit to see if it crashes immediately?
        try:
            rank = proc.wait(timeout=2)
            # If it exited in < 2 seconds, it failed
            if rank != 0:
                print(f"[music] Pipeline failed (valid exit code {rank}). Updating yt-dlp...", flush=True)
                update_ytdlp()
                # Retry once
                proc = subprocess.Popen(pipeline_cmd, shell=True)
        except subprocess.TimeoutExpired:
            # It's running fine (streaming)
            pass
            
        # Add to index
        index[vid_id] = {
            "title": title,
            "queries": [norm_query]
        }
        with open(index_path, "w") as f:
            json.dump(index, f, indent=2)
            
        return proc
        
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
