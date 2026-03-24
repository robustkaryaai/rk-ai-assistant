"""Music streaming - instant playback with mpg123."""

import subprocess
import shutil
import os
import json
import re
import time
from .audio_utils import speak
import signal
import threading
from typing import Optional, List, Dict, Any
from difflib import SequenceMatcher

from threading import Lock

current_player = None
current_track_info = None
prefetched_track_info = None
last_played_query = None
_search_lock = Lock() # 🚀 Prevent duplicate overlapping searches
_state_lock = Lock()
_prefetch_lock = Lock()
_housekeeping_lock = Lock()
_music_state = "idle"
_playlist_generation = 0
_housekeeping_started = False

_STATUS_UNSET = object()
_SUPPORTED_EXTS = ("mp3", "m4a", "webm")

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

def _has_stop_command(norm_query: str) -> bool:
    """Detect an explicit stop/cancel command, not ordinary words like 'official'."""
    if not norm_query:
        return False

    patterns = [
        r"\bstop\b",
        r"\boff\b",
        r"\bcancel\b",
        r"\bshut\s+up\b",
        r"\bquiet\b",
    ]
    return any(re.search(pattern, norm_query) for pattern in patterns)


def _songs_dir():
    from pathlib import Path
    cache_dir = Path(os.getcwd()) / "songs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _index_path():
    return _songs_dir() / "index.json"


def _stats_path():
    return _songs_dir() / "track_stats.json"


def _load_json_file(path, default):
    try:
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"[music] JSON load error for {path.name}: {e}", flush=True)
    return default


def _save_json_file(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[music] JSON save error for {path.name}: {e}", flush=True)


def _safe_title(title: str) -> str:
    return "".join(c for c in str(title or "") if c.isalnum() or c in (" ", "-", "_")).strip() or "track"


def _short_title(title: str) -> str:
    speak_title = str(title or "").partition("|")[0].strip()
    words = speak_title.split()
    return " ".join(words[:5]) if len(words) > 5 else speak_title


def _announce_title(title: str) -> str:
    short = _short_title(title)
    return short or "music"


def _get_slug() -> Optional[str]:
    try:
        from .networking import read_slug
        slug, _ = read_slug()
        return slug
    except Exception:
        return None


def _push_backend_status(busy_state=None, download_progress=_STATUS_UNSET):
    try:
        from .config import BACKEND_BASE_URL
        import requests
        slug = _get_slug()
        if not slug:
            return

        payload = {}
        if busy_state is not None:
            payload["busyState"] = busy_state
        if download_progress is not _STATUS_UNSET:
            payload["downloadProgress"] = download_progress
        if not payload:
            return
        requests.post(f"{BACKEND_BASE_URL}/device/{slug}/update-status", json=payload, timeout=3)
    except Exception as e:
        print(f"[music] Backend status push failed: {e}", flush=True)


def _set_music_state(state: str, download_progress=_STATUS_UNSET):
    global _music_state
    with _state_lock:
        _music_state = state
    _push_backend_status(busy_state=state, download_progress=download_progress)


def get_runtime_state() -> Optional[str]:
    with _state_lock:
        return _music_state if _music_state in {"searching", "downloading", "playing"} else None


def _clear_download_progress():
    _push_backend_status(download_progress=None)


def _extract_vid_id(filename: str) -> Optional[str]:
    match = re.search(r"\[([a-zA-Z0-9_-]+)\]\.(mp3|m4a|webm)$", filename)
    if match:
        return match.group(1)
    match = re.search(r"^([a-zA-Z0-9_-]+)\.(mp3|m4a|webm)$", filename)
    if match:
        return match.group(1)
    return None


def _find_cached_file(vid_id: str):
    cache_dir = _songs_dir()
    import glob
    matches = []
    for ext in _SUPPORTED_EXTS:
        matches.extend(list(cache_dir.glob(f"*{glob.escape(vid_id)}*.{ext}")))
    if matches:
        return str(matches[0])
    for ext in _SUPPORTED_EXTS:
        exact = cache_dir / f"{vid_id}.{ext}"
        if exact.exists():
            return str(exact)
    return None


def _load_index() -> Dict[str, Dict[str, Any]]:
    return _load_json_file(_index_path(), {})


def _save_index(index: Dict[str, Dict[str, Any]]):
    _save_json_file(_index_path(), index)


def _append_query_to_index(vid_id: str, title: str, norm_query: str):
    index = _load_index()
    current_data = index.get(vid_id, {})
    queries = current_data.get("queries", [])
    if norm_query and norm_query not in queries:
        queries.append(norm_query)
    index[vid_id] = {"title": title, "queries": queries}
    _save_index(index)


def _record_play(track: Dict[str, Any]):
    vid_id = track.get("vid_id")
    if not vid_id:
        return
    stats = _load_json_file(_stats_path(), {})
    entry = stats.get(vid_id, {})
    entry["title"] = track.get("title", "")
    entry["file_path"] = track.get("file_path", "")
    entry["play_count"] = int(entry.get("play_count", 0)) + 1
    entry["last_played_at"] = int(time.time())
    stats[vid_id] = entry
    _save_json_file(_stats_path(), stats)


def _spawn_player(file_path: str):
    if not file_path or not os.path.exists(file_path):
        return None

    player_cmds = []
    if shutil.which("cvlc"):
        player_cmds.append(["cvlc", "--play-and-exit", "--no-video", "--quiet", file_path])
    if shutil.which("vlc"):
        player_cmds.append(["vlc", "--play-and-exit", "--no-video", "--quiet", file_path])
    if shutil.which("ffplay"):
        player_cmds.append(["ffplay", "-autoexit", "-nodisp", "-loglevel", "quiet", file_path])
    if shutil.which("mpg123"):
        player_cmds.append(["mpg123", "-q", file_path])

    for cmd in player_cmds:
        try:
            return subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            print(f"[music] Player launch failed for {cmd[0]}: {e}", flush=True)

    print("[music] No supported background audio player found.", flush=True)
    return None


def _resolve_local_track(norm_query: str) -> Optional[Dict[str, Any]]:
    index = _load_index()
    if not index:
        return None

    best_match = None
    best_score = 0.0
    for vid_id, data in index.items():
        title = data.get("title", "").lower()
        if not title:
            continue

        for pq in data.get("queries", []):
            pq_clean = clean_music_query(pq)
            score_q = SequenceMatcher(None, norm_query, pq_clean).ratio()
            if score_q > best_score:
                best_score = score_q
                best_match = vid_id
            score_raw = SequenceMatcher(None, norm_query, pq).ratio()
            if score_raw > best_score:
                best_score = score_raw
                best_match = vid_id

        score1 = SequenceMatcher(None, norm_query, title).ratio()
        q_words = set(norm_query.split())
        t_words = set(title.split())
        score2 = (len(q_words.intersection(t_words)) / len(q_words)) if q_words else 0.0
        current_score = max(score1, score2)
        if current_score > best_score:
            best_score = current_score
            best_match = vid_id
        if norm_query in title or title in norm_query:
            best_score = max(best_score, 0.8)

    if best_score <= 0.6 or not best_match:
        return None

    found_file = _find_cached_file(best_match)
    if not found_file:
        return None

    title = index.get(best_match, {}).get("title", best_match)
    print(f"[music] ✅ Found local match! Score: {best_score:.2f} (ID: {best_match})", flush=True)
    _append_query_to_index(best_match, title, norm_query)
    return {
        "vid_id": best_match,
        "title": title,
        "file_path": found_file,
        "query": norm_query,
        "source": "local",
    }


def _search_youtube_match(norm_query: str) -> Optional[Dict[str, str]]:
    search_cmd = [
        "yt-dlp",
        "--force-ipv4",
        "--get-title",
        "--get-id",
        f"ytsearch1:{norm_query}",
    ]
    search_res = subprocess.run(search_cmd, capture_output=True, text=True)
    if search_res.returncode != 0:
        return None
    lines = search_res.stdout.strip().split("\n")
    if len(lines) < 2:
        return None
    return {"title": lines[0].strip(), "vid_id": lines[1].strip()}


def _download_track(track: Dict[str, Any], first_song: bool = False) -> Optional[Dict[str, Any]]:
    cache_dir = _songs_dir()
    title = track["title"]
    vid_id = track["vid_id"]
    safe_title = _safe_title(title)
    file_path_template = str(cache_dir / f"{safe_title} [{vid_id}].%(ext)s"[:255])
    safe_url = f"https://www.youtube.com/watch?v={vid_id}"

    if first_song:
        speak(f"Downloading {_announce_title(title)}")
        _set_music_state("downloading", f"Downloading: {title}")
    else:
        _push_backend_status(download_progress=f"Downloading next: {title}")

    print(f"[music] ⬇️  Downloading... ({title})", flush=True)
    dl_cmd = [
        "yt-dlp", "--quiet", "--no-warnings", "--force-ipv4",
        "-f", "ba[ext=m4a]/ba", "-o", file_path_template, safe_url,
    ]
    subprocess.run(dl_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    final_file = _find_cached_file(vid_id)
    if not final_file:
        if first_song:
            _clear_download_progress()
        return None

    track = dict(track)
    track["file_path"] = final_file
    _append_query_to_index(vid_id, title, track.get("query", ""))
    _clear_download_progress()
    return track


def _prepare_track(norm_query: str, announce: bool = True, prefetch: bool = False) -> Optional[Dict[str, Any]]:
    if not norm_query:
        return None

    local_track = _resolve_local_track(norm_query)
    if local_track:
        return local_track

    if not _search_lock.acquire(blocking=False):
        print(f"[music] ✋ Search already in progress. Skipping duplicate search for: {norm_query}")
        return None

    try:
        if announce:
            speak(f"Searching for {norm_query}")
            _set_music_state("searching", None)
        else:
            _push_backend_status(download_progress=f"Searching next: {norm_query}")

        match = _search_youtube_match(norm_query)
        if not match:
            _clear_download_progress()
            return None

        title = match["title"]
        vid_id = match["vid_id"]
        print(f"[music] ✓ Found: {title} ({vid_id})", flush=True)
        cached_file = _find_cached_file(vid_id)
        track = {
            "vid_id": vid_id,
            "title": title,
            "file_path": cached_file,
            "query": norm_query,
            "source": "youtube",
        }
        _append_query_to_index(vid_id, title, norm_query)

        if cached_file and os.path.exists(cached_file):
            _clear_download_progress()
            return track

        return _download_track(track, first_song=announce and not prefetch)
    finally:
        _search_lock.release()


def _prefetch_next_track(finished_track: Dict[str, Any], generation: int):
    global prefetched_track_info
    suggestion = get_related_song_recommendation(finished_track.get("title", ""))
    if not suggestion:
        return
    suggestion_query = clean_music_query(suggestion)
    if not suggestion_query:
        return
    print(f"[music] 🔮 Prefetching next suggestion: {suggestion_query}", flush=True)
    next_track = _prepare_track(suggestion_query, announce=False, prefetch=True)
    if not next_track:
        return
    with _prefetch_lock:
        if generation != _playlist_generation:
            return
        if current_track_info and next_track.get("vid_id") == current_track_info.get("vid_id"):
            return
        prefetched_track_info = next_track
        print(f"[music] ✅ Next track ready: {next_track.get('title')}", flush=True)


def _start_prefetch_thread(track: Dict[str, Any], generation: int):
    threading.Thread(
        target=_prefetch_next_track,
        args=(dict(track), generation),
        daemon=True,
        name=f"music-prefetch-{generation}",
    ).start()


def _on_track_finished(proc, generation: int):
    global current_player, current_track_info, prefetched_track_info
    try:
        proc.wait()
    except Exception:
        return

    if generation != _playlist_generation:
        return
    if current_player is not proc:
        return

    with _prefetch_lock:
        next_track = prefetched_track_info
        prefetched_track_info = None

    if next_track:
        print(f"[music] ▶️  Autoplaying prefetched track: {next_track.get('title')}", flush=True)
        _play_track(next_track, announce_mode="silent", generation=generation, allow_prefetch=True)
        return

    current_player = None
    current_track_info = None
    _set_music_state("idle", None)


def _play_track(track: Dict[str, Any], announce_mode: str = "now_playing", generation: int = 0, allow_prefetch: bool = True):
    global current_player, current_track_info
    if announce_mode == "now_playing":
        speak(f"Now playing {_announce_title(track.get('title', 'music'))}")

    proc = _spawn_player(track.get("file_path"))
    if not proc:
        return None

    current_player = proc
    current_track_info = dict(track)
    _record_play(track)
    _set_music_state("playing", None)
    if allow_prefetch:
        _start_prefetch_thread(track, generation)
    threading.Thread(
        target=_on_track_finished,
        args=(proc, generation),
        daemon=True,
        name=f"music-monitor-{generation}",
    ).start()
    return proc


def _stop_current_process():
    global current_player
    try:
        if current_player and current_player.poll() is None:
            current_player.terminate()
            current_player.wait(timeout=2)
    except Exception:
        pass


def start_music_housekeeping():
    global _housekeeping_started
    with _housekeeping_lock:
        if _housekeeping_started:
            return
        _housekeeping_started = True
        threading.Thread(target=_music_housekeeping_loop, daemon=True, name="music-housekeeping").start()


def _music_housekeeping_loop():
    while True:
        try:
            _cleanup_local_music_if_low_storage()
        except Exception as e:
            print(f"[music] Housekeeping error: {e}", flush=True)
        time.sleep(60)


def _cleanup_local_music_if_low_storage():
    cache_dir = _songs_dir()
    files = []
    for ext in _SUPPORTED_EXTS:
        files.extend(list(cache_dir.glob(f"*.{ext}")))
    if not files:
        return

    low_storage_mb = int(os.getenv("RK_MUSIC_LOW_STORAGE_MB", "512"))
    cache_limit_mb = int(os.getenv("RK_MUSIC_CACHE_LIMIT_MB", "2048"))
    disk_free_mb = shutil.disk_usage(str(cache_dir)).free / (1024 * 1024)
    total_cache_mb = sum(f.stat().st_size for f in files if f.exists()) / (1024 * 1024)
    if disk_free_mb >= low_storage_mb and total_cache_mb <= cache_limit_mb:
        return

    stats = _load_json_file(_stats_path(), {})
    index = _load_index()
    current_file = (current_track_info or {}).get("file_path")
    prefetched_file = (prefetched_track_info or {}).get("file_path")

    def _candidate_sort(path_obj):
        vid_id = _extract_vid_id(path_obj.name) or path_obj.stem
        entry = stats.get(vid_id, {})
        return (
            0 if int(entry.get("play_count", 0)) <= 1 else 1,
            int(entry.get("play_count", 0)),
            int(entry.get("last_played_at", 0)),
        )

    for path_obj in sorted(files, key=_candidate_sort):
        if str(path_obj) in {current_file, prefetched_file}:
            continue
        if disk_free_mb >= low_storage_mb and total_cache_mb <= cache_limit_mb:
            break
        try:
            size_mb = path_obj.stat().st_size / (1024 * 1024)
            vid_id = _extract_vid_id(path_obj.name) or path_obj.stem
            path_obj.unlink(missing_ok=True)
            stats.pop(vid_id, None)
            index.pop(vid_id, None)
            total_cache_mb = max(0.0, total_cache_mb - size_mb)
            disk_free_mb = shutil.disk_usage(str(cache_dir)).free / (1024 * 1024)
            print(f"[music] 🧹 Removed cached track: {path_obj.name}", flush=True)
        except Exception as e:
            print(f"[music] Cache cleanup failed for {path_obj.name}: {e}", flush=True)

    _save_json_file(_stats_path(), stats)
    _save_index(index)

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
                 return _spawn_player(found_file)
        
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
                return _spawn_player(file_path)
            else:
                return _spawn_player(file_path)
        
        # Download completely (native format, no transcoding, totally silent)
        speak_title = title.partition('|')[0]
        words = speak_title.split()
        if len(words) > 5: speak_title = " ".join(words[:5])
        speak(f"Downloading {speak_title}")
        print(f"[music] ⬇️  Downloading fast... ({title})", flush=True)
        
        # 🚀 REPORT DOWNLOAD STATUS TO BACKEND
        try:
            from .networking import read_slug, BACKEND_BASE_URL
            import requests
            slug = read_slug()
            if slug:
                requests.post(f"{BACKEND_BASE_URL}/device/{slug}/update-status", json={"downloadProgress": f"Downloading: {title}"}, timeout=2)
        except:
            pass
        
        safe_url = f"https://www.youtube.com/watch?v={vid_id}"
        
        dl_cmd = [
            "yt-dlp", "--quiet", "--no-warnings", "--force-ipv4", 
            "-f", "ba[ext=m4a]/ba", "-o", file_path_template, safe_url
        ]
        
        subprocess.run(dl_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # 🚀 CLEAR DOWNLOAD STATUS
        try:
            if slug:
                requests.post(f"{BACKEND_BASE_URL}/device/{slug}/update-status", json={"downloadProgress": None}, timeout=2)
        except:
            pass
        
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
            return _spawn_player(final_file)
        else:
            return _spawn_player(final_file)

    except Exception as e:
        print(f"[music] ❌ Error: {e}", flush=True)
        return None
    finally:
        _search_lock.release()

def play_music(query: str):
    """
    Stream music directly to mpg123 (works with Bluetooth, instant playback).
    """
    global current_player, last_played_query, prefetched_track_info, _playlist_generation
    
    # Check dependencies
    if not shutil.which("yt-dlp"):
        print("[music] Install yt-dlp: sudo wget https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -O /usr/local/bin/yt-dlp && sudo chmod a+rx /usr/local/bin/yt-dlp", flush=True)
        return None
    
    norm_query = clean_music_query(query)
    print(f"[music] 🧹 Cleaned Query: '{norm_query}' (Original: '{query}')", flush=True)

    # 🚀 HANDLE STOP COMMANDS EXPLICITLY
    if _has_stop_command(norm_query):
        print("[music] 🛑 Stop command detected. Terminating playback.")
        stop_music()
        return None
    
    _playlist_generation += 1
    generation = _playlist_generation
    prefetched_track_info = None
    _stop_current_process()

    last_played_query = query
    track = _prepare_track(norm_query, announce=True, prefetch=False)
    if not track:
        _set_music_state("idle", None)
        speak("I couldn't find that song.")
        return None

    proc = _play_track(track, announce_mode="now_playing", generation=generation, allow_prefetch=True)
    if proc:
        current_player = proc
        return proc

    _set_music_state("idle", None)
    speak("I couldn't play that song.")
    return None

def stop_music():
    """Stop music."""
    global current_player, current_track_info, prefetched_track_info, _playlist_generation

    _playlist_generation += 1
    prefetched_track_info = None
    current_track_info = None
    _stop_current_process()
    
    # Force kill
    subprocess.run(["pkill", "-9", "vlc"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "cvlc"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "ffplay"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "mpv"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "mpg123"], stderr=subprocess.DEVNULL)

    current_player = None
    _set_music_state("idle", None)
    _clear_download_progress()
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
            file_ext = f.suffix.lower().lstrip(".")
            
            # Regex 1: ... [ID].mp3 / .m4a / .webm
            # YouTube IDs are typically 11 chars, but can vary.
            # Look for [ID] pattern at end for any supported media extension.
            m = re.search(r"\[([a-zA-Z0-9_-]+)\]\.(mp3|m4a|webm)$", filename)
            if m:
                vid_id = m.group(1)
            else:
                # Regex 2: ID.mp3 (Raw ID)
                # Assume filename IS the ID if no brackets
                # Limit to typical ID chars
                m = re.search(r"^([a-zA-Z0-9_-]+)\.(mp3|m4a|webm)$", filename)
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
                                if filename == f"{vid_id}.{file_ext}":
                                     safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
                                     new_name = f"{safe_title} [{vid_id}].{file_ext}"[:255]
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
