"""Music streaming - instant playback with mpg123."""

import subprocess
import shutil
import os
import json
from .audio_utils import speak
import signal
from typing import Optional, List, Dict, Any
from difflib import SequenceMatcher

from threading import Lock

current_player = None
last_played_query = None
_search_lock = Lock() # 🚀 Prevent duplicate overlapping searches

def get_related_song_recommendation(title: str) -> Optional[str]:
    """Use Gemini to get a related song title based on the current one."""
    from .gemini_client import classify_intent, GEMINI_AVAILABLE
    from .config import GEMINI_API_KEY, GEMINI_MODEL_PRIMARY
    
    if not GEMINI_AVAILABLE:
        return None
        
    prompt = f"The user is listening to '{title}'. Suggest one similar or related song title only. Output strictly the song name and artist, nothing else. No punctuation, no prose."
    
    # We can reuse classify_intent but it returns JSON. 
    # Let's add a simple text call or use conversational response.
    from .gemini_client import get_conversational_response
    suggestion = get_conversational_response(prompt, api_key=GEMINI_API_KEY, model_name=GEMINI_MODEL_PRIMARY)
    
    if suggestion and "Sorry" not in suggestion and "I'm having trouble" not in suggestion:
        return suggestion.strip()
    return None


def clean_music_query(query):
    """Remove common filler words and STT artifacts."""
    if not query: return ""
    norm_query = query.lower().strip()
    
    # Common words to remove
    ignore_words = [
        "play", "song", "from", "youtube", "please", "can you", "i want to hear",
        "plate", "place", "pleas", "plait", # STT errors for 'play'
        "search", "find"
    ]
    
    clean_q = norm_query
    for word in ignore_words:
        # Remove whole words only
        clean_q = clean_q.replace(f" {word} ", " ")
        if clean_q.startswith(f"{word} "):
            clean_q = clean_q[len(word)+1:]
        if clean_q.endswith(f" {word}"):
            clean_q = clean_q[:-len(word)-1]
            
    return clean_q.strip()

def search_local_and_play(norm_query):
    """
    Search local JSON index for fuzzy match using cleaned query.
    Returns: process (subprocess.Popen) if found and played, else None.
    """
    try:
        from pathlib import Path
        cache_dir = Path(os.getcwd()) / "songs"
        index_path = cache_dir / "index.json"
        
        if not index_path.exists():
            return None
            
        import json
        try:
            with open(index_path, "r") as f:
                index = json.load(f)
        except:
            return None

        # Fuzzy match query against titles or stored queries
        best_match = None
        best_score = 0.0
        
        for vid_id, data in index.items():
            # Check against title
            title = data.get("title", "").lower()
            if not title: continue
            
            # Check against stored queries (Iterate all queries for this ID)
            previous_queries = data.get("queries", [])
            for pq in previous_queries:
                # IMPORTANT: Clean stored query too for comparisons?
                # Or compare raw stored query vs clean input?
                # User had success with fuzzy matching raw stored query vs clean input.
                # So let's fuzzy match against raw stored query.
                pq_clean = clean_music_query(pq) # Actually, clean stored query helps match clean input
                
                # Match against cleanly stored query
                score_q = SequenceMatcher(None, norm_query, pq_clean).ratio()
                if score_q > best_score:
                    best_score = score_q
                    best_match = vid_id
                
                # Also match against RAW stored query (for legacy index entries)
                score_raw = SequenceMatcher(None, norm_query, pq).ratio()
                if score_raw > best_score:
                    best_score = score_raw
                    best_match = vid_id
                
            # Fuzzy title match
            score1 = SequenceMatcher(None, norm_query, title).ratio()
            
            # Keyword match
            q_words = set(norm_query.split())
            t_words = set(title.split())
            intersection = q_words.intersection(t_words)
            
            score2 = 0.0
            if q_words:
                 score2 = len(intersection) / len(q_words)
                 
            current_score = max(score1, score2)
            if current_score > best_score:
                best_score = current_score
                best_match = vid_id

            # Boost if query is substring
            if norm_query in title or title in norm_query:
                 if 0.8 > best_score: best_score = 0.8
                 
        if best_score > 0.6 and best_match:
             print(f"[music] ✅ Found local match! Score: {best_score:.2f} (ID: {best_match})", flush=True)
             data = index[best_match]
             
             # Search for file (Escape brackets in ID for glob)
             import glob
             escaped_id = glob.escape(best_match)
             matches = []
             for ext in ["mp3", "m4a", "webm"]:
                 matches.extend(list(cache_dir.glob(f"*{escaped_id}*.{ext}")))
                 
             found_file = str(matches[0]) if matches else None
             
             if not found_file:
                 # Try exact fallback
                 for ext in ["mp3", "m4a", "webm"]:
                     possible = cache_dir / f"{best_match}.{ext}"
                     if possible.exists(): 
                         found_file = str(possible)
                         break
                 
             if found_file:
                 # Shorten title for speaking
                 speak_title = data['title']
                 if "|" in speak_title: speak_title = speak_title.split("|")[0]
                 words = speak_title.split()
                 if len(words) > 5: speak_title = " ".join(words[:5])
                    
                 speak(f"Playing {speak_title}")
                 
                 # Store CLEAN query in index
                 if norm_query not in data.get("queries", []):
                     data.setdefault("queries", []).append(norm_query)
                     with open(index_path, "w") as f:
                         json.dump(index, f, indent=2)

                 # Play using appropriate player
                 if found_file.endswith(".mp3"):
                     cmd = ["mpg123", "-o", "pulse", "-q", found_file]
                     return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                 else:
                     # For m4a/webm, use fast lightweight ffmpeg pipe to paplay/aplay (zero encoding overhead)
                     pipeline = f"ffmpeg -hide_banner -loglevel error -i '{found_file}' -f wav - | paplay 2>/dev/null || ffmpeg -hide_banner -loglevel error -i '{found_file}' -f wav - | aplay -D pulse -q 2>/dev/null"
                     return subprocess.Popen(pipeline, shell=True, preexec_fn=os.setsid)
        
        return None
        
    except Exception as e:
        print(f"[music] Local search error: {e}")
        return None

def search_youtube_and_play(norm_query):
    """Search YouTube, download, cache, and play."""
    if not _search_lock.acquire(blocking=False):
        print(f"[music] ✋ Search already in progress. Skipping duplicate search for: {norm_query}")
        return None
        
    try:
        from pathlib import Path
        cache_dir = Path(os.getcwd()) / "songs"
        index_path = cache_dir / "index.json"
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"[music] 🌍 Searching YouTube for: {norm_query}", flush=True)
        speak(f"Searching online for {norm_query}")
        
        search_cmd = [
            "yt-dlp", 
            "--force-ipv4", 
            "--get-title", "--get-id", 
            f"ytsearch1:{norm_query}"
        ]
        search_res = subprocess.run(search_cmd, capture_output=True, text=True)
        
        if search_res.returncode != 0:
             print("[music] Error finding song", flush=True)
             speak("I couldn't find that song.")
             return None
             
        lines = search_res.stdout.strip().split('\n')
        if len(lines) < 2:
            print("[music] ❌ No results or malformed output", flush=True)
            speak("I couldn't find that song.")
            return None
            
        title = lines[0]
        vid_id = lines[1]
        
        # Remove illegal filename chars (especially slashes)
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        filename_template = f"{safe_title} [{vid_id}].%(ext)s"[:255]
        file_path_template = str(cache_dir / filename_template)
        
        print(f"[music] ✓ Found: {title} ({vid_id})", flush=True)

        # Look for existing downloaded files (m4a, mp3, webm)
        import glob
        existing_matches = []
        for ext in ["mp3", "m4a", "webm"]:
            existing_matches.extend(list(cache_dir.glob(f"*{glob.escape(vid_id)}*.{ext}")))
            
        file_path = str(existing_matches[0]) if existing_matches else None

        # Check for old cache format
        if not file_path:
            for ext in ["mp3", "m4a", "webm"]:
                old_path = str(cache_dir / f"{vid_id}.{ext}")
                if os.path.exists(old_path):
                    try: 
                        new_name = f"{safe_title} [{vid_id}].{ext}"[:255]
                        os.rename(old_path, str(cache_dir / new_name))
                        file_path = str(cache_dir / new_name)
                    except: pass
                    break

        # Load index
        index = {}
        if index_path.exists():
            try:
                with open(index_path, "r") as f: index = json.load(f)
            except: pass

        if file_path and os.path.exists(file_path):
            print(f"[music] 📂 Playing from file cache: {file_path}", flush=True)
            # Add to index (Clean query)
            current_data = index.get(vid_id, {})
            existing_queries = current_data.get("queries", [])
            if norm_query not in existing_queries:
                 existing_queries.append(norm_query)
                 
            index[vid_id] = {"title": title, "queries": existing_queries}
            with open(index_path, "w") as f:
                json.dump(index, f, indent=2)
                
            global last_played_query
            last_played_query = norm_query # Store for autoplay/replay
            
            # Shorten title for speaking
            speak_title = title.partition('|')[0]
            words = speak_title.split()
            if len(words) > 5: speak_title = " ".join(words[:5])
            speak(f"Playing {speak_title}")
            
            if file_path.endswith(".mp3"):
                return subprocess.Popen(["mpg123", "-o", "pulse", "-q", file_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                pipeline = f"ffmpeg -hide_banner -loglevel error -i '{file_path}' -f wav - | paplay 2>/dev/null || ffmpeg -hide_banner -loglevel error -i '{file_path}' -f wav - | aplay -D pulse -q 2>/dev/null"
                return subprocess.Popen(pipeline, shell=True, preexec_fn=os.setsid)
        
        # Download completely (native format, no transcoding, totally silent)
        speak_title = title.partition('|')[0]
        words = speak_title.split()
        if len(words) > 5: speak_title = " ".join(words[:5])
        speak(f"Downloading {speak_title}")
        print(f"[music] ⬇️  Downloading fast... ({title})", flush=True)
        
        safe_url = f"https://www.youtube.com/watch?v={vid_id}"
        
        dl_cmd = [
            "yt-dlp", "--quiet", "--no-warnings", "--force-ipv4", 
            "-f", "ba[ext=m4a]/ba", "-o", file_path_template, safe_url
        ]
        
        subprocess.run(dl_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Now find the downloaded file
        new_matches = []
        for ext in ["mp3", "m4a", "webm"]:
            new_matches.extend(list(cache_dir.glob(f"*{glob.escape(vid_id)}*.{ext}")))
            
        final_file = str(new_matches[0]) if new_matches else None
        
        if not final_file:
            print("[music] ❌ Download failed.", flush=True)
            speak("I couldn't complete the download.")
            return None
        
        # Add to index (Clean query)
        current_data = index.get(vid_id, {})
        existing_queries = current_data.get("queries", [])
        if norm_query not in existing_queries:
             existing_queries.append(norm_query)
             
        index[vid_id] = {"title": title, "queries": existing_queries}
        with open(index_path, "w") as f:
            json.dump(index, f, indent=2)
            
        # Play the newly downloaded file
        print(f"[music] ▶️  Playing...", flush=True)
        if final_file.endswith(".mp3"):
            return subprocess.Popen(["mpg123", "-o", "pulse", "-q", final_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            pipeline = f"ffmpeg -hide_banner -loglevel error -i '{final_file}' -f wav - | paplay 2>/dev/null || ffmpeg -hide_banner -loglevel error -i '{final_file}' -f wav - | aplay -D pulse -q 2>/dev/null"
            return subprocess.Popen(pipeline, shell=True, preexec_fn=os.setsid)

    except Exception as e:
        print(f"[music] ❌ Error: {e}", flush=True)
        return None
    finally:
        _search_lock.release()

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
    
    norm_query = clean_music_query(query)
    print(f"[music] 🧹 Cleaned Query: '{norm_query}' (Original: '{query}')", flush=True)
    
    global last_played_query
    last_played_query = query # Store the original query for 'play again'
    
    # 2. Try Local
    proc = search_local_and_play(norm_query)
    if proc:
        current_player = proc
        return proc
        
    # 3. Try Online
    proc = search_youtube_and_play(norm_query)
    if proc:
        current_player = proc
        return proc
        
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

def sync_music_index():
    """Sync index.json with actual files in songs/ directory."""
    try:
        from pathlib import Path
        import re
        cache_dir = Path(os.getcwd()) / "songs"
        index_path = cache_dir / "index.json"
        
        if not cache_dir.exists(): return
        
        import json
        index = {}
        if index_path.exists():
            try:
                with open(index_path, "r") as f:
                    index = json.load(f)
            except: pass
            
        files = []
        for ext in ["mp3", "m4a", "webm"]:
            files.extend(list(cache_dir.glob(f"*.{ext}")))
        updated = False
        
        print(f"[music] 🔄 Syncing music index ({len(files)} files)...", flush=True)
        
        for f in files:
            filename = f.name
            vid_id = None
            
            # Regex 1: ... [ID].mp3
            # YouTube IDs are typically 11 chars, but can vary. 
            # Look for [ID] pattern at end.
            m = re.search(r"\[([a-zA-Z0-9_-]+)\]\.mp3$", filename)
            if m:
                vid_id = m.group(1)
            else:
                # Regex 2: ID.mp3 (Raw ID)
                # Assume filename IS the ID if no brackets
                # Limit to typical ID chars
                m = re.search(r"^([a-zA-Z0-9_-]+)\.mp3$", filename)
                if m:
                     vid_id = m.group(1)
                     
            if vid_id:
                # If valid ID and NOT in index
                if vid_id not in index:
                    print(f"[music] ❓ Indexing missing song: {filename} (ID: {vid_id})", flush=True)
                    # Fetch title
                    try:
                        cmd = [
                            "yt-dlp", 
                            "--force-ipv4", 
                            "--get-title", 
                            f"https://www.youtube.com/watch?v={vid_id}"
                        ]
                        res = subprocess.run(cmd, capture_output=True, text=True)
                        
                        if res.returncode == 0:
                            title = res.stdout.strip()
                            if title:
                                # Add to index with NO queries (since we don't know what user would ask)
                                # But title match will work!
                                index[vid_id] = {"title": title, "queries": []}
                                updated = True
                                print(f"[music] ✓ Added to index: {title}", flush=True)
                                
                                # Rename if raw ID (ID.mp3 -> Title [ID].mp3)
                                if filename == f"{vid_id}.mp3":
                                     safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
                                     new_name = f"{safe_title} [{vid_id}].mp3"[:255]
                                     try:
                                         f.rename(cache_dir / new_name)
                                         print(f"[music] 📂 Renamed to: {new_name}", flush=True)
                                     except: pass
                        else:
                             print(f"[music] ❌ Failed to get title for {vid_id}", flush=True)
                    except Exception as e:
                        print(f"[music] Error fetching title for {vid_id}: {e}", flush=True)
                        
        if updated:
             with open(index_path, "w") as f:
                 json.dump(index, f, indent=2)
             print("[music] ✅ Index sync complete.", flush=True)
        else:
             print("[music] Index is up to date.", flush=True)
             
    except Exception as e:
        print(f"[music] Index sync error: {e}", flush=True)
