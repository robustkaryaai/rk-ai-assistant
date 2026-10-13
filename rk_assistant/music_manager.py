"""Simplified music manager for RK AI.

Goals:
- Prefer local cached songs first.
- Use yt-dlp with cookie support when a song is not cached.
- Keep the public API used by the assistant intact.
- Avoid heavy background work while music is playing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

from .audio_utils import ensure_bluetooth_audio_route, speak

current_player = None
current_track_info = None
last_played_query = None

_music_state = "idle"
_state_lock = threading.Lock()
_player_lock = threading.Lock()
_housekeeping_started = False
_housekeeping_lock = threading.Lock()

_SUPPORTED_EXTS = ("mp3", "m4a", "webm", "mp4", "opus", "ogg", "mkv")


def _songs_dir() -> Path:
    cache_dir = Path(os.getcwd()) / "songs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _index_path() -> Path:
    return _songs_dir() / "index.json"


def _stats_path() -> Path:
    return _songs_dir() / "track_stats.json"


def _load_json_file(path: Path, default: Any):
    try:
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"[music] JSON load error for {path.name}: {e}", flush=True)
    return default


def _save_json_file(path: Path, data: Any) -> None:
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[music] JSON save error for {path.name}: {e}", flush=True)


def _safe_title(title: str) -> str:
    return "".join(c for c in str(title or "") if c.isalnum() or c in (" ", "-", "_")).strip() or "track"


def _short_title(title: str) -> str:
    short = str(title or "").partition("|")[0].strip()
    words = short.split()
    return " ".join(words[:5]) if len(words) > 5 else short


def _announce_title(title: str) -> str:
    return _short_title(title) or "music"


def _clean_query(query: str) -> str:
    if not query:
        return ""
    text = query.lower().strip()
    noise = [
        "play", "song", "songs", "from", "youtube", "on youtube", "please",
        "search", "find", "music", "video", "track",
    ]
    for word in noise:
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _has_stop_command(norm_query: str) -> bool:
    return bool(re.search(r"\b(stop|cancel|pause|shut up|quiet|silence|off)\b", norm_query or ""))


def _get_slug() -> Optional[str]:
    try:
        from .networking import read_slug
        slug, _ = read_slug()
        return slug
    except Exception:
        return None


def _set_music_state(state: str) -> None:
    global _music_state
    with _state_lock:
        _music_state = state


def get_runtime_state() -> Optional[str]:
    with _state_lock:
        return _music_state if _music_state in {"searching", "downloading", "playing"} else None


def _extract_vid_id(filename: str) -> Optional[str]:
    match = re.search(r"\[([a-zA-Z0-9_-]+)\]\.(mp3|m4a|webm|mp4|opus|ogg|mkv)$", filename)
    if match:
        return match.group(1)
    match = re.search(r"^([a-zA-Z0-9_-]+)\.(mp3|m4a|webm|mp4|opus|ogg|mkv)$", filename)
    if match:
        return match.group(1)
    return None


def _find_cached_file(vid_id: str) -> Optional[str]:
    cache_dir = _songs_dir()
    import glob
    for ext in _SUPPORTED_EXTS:
        matches = list(cache_dir.glob(f"*{glob.escape(vid_id)}*.{ext}"))
        if matches:
            return str(matches[0])
    for ext in _SUPPORTED_EXTS:
        exact = cache_dir / f"{vid_id}.{ext}"
        if exact.exists():
            return str(exact)
    return None


def _load_index() -> Dict[str, Dict[str, Any]]:
    return _load_json_file(_index_path(), {})


def _save_index(index: Dict[str, Dict[str, Any]]) -> None:
    _save_json_file(_index_path(), index)


def _append_query_to_index(vid_id: str, title: str, norm_query: str) -> None:
    index = _load_index()
    current = index.get(vid_id, {})
    queries = current.get("queries", [])
    if norm_query and norm_query not in queries:
        queries.append(norm_query)
    index[vid_id] = {"title": title, "queries": queries}
    _save_index(index)


def _score_text_match(query: str, title: str, queries: List[str]) -> float:
    score = SequenceMatcher(None, query, title).ratio()
    for known_query in queries:
        score = max(score, SequenceMatcher(None, query, known_query).ratio())
    query_words = set(query.split())
    title_words = set(title.split())
    if query_words and title_words:
        overlap = len(query_words & title_words) / max(len(query_words | title_words), 1)
        score = max(score, overlap)
    return score


def _resolve_local_track(norm_query: str) -> Optional[Dict[str, Any]]:
    if not norm_query:
        return None

    index = _load_index()
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0

    query_words = set(norm_query.split())

    for vid_id, meta in index.items():
        title = str(meta.get("title", "")).strip().lower()
        queries = [str(q).strip().lower() for q in meta.get("queries", []) if str(q).strip()]

        cached_file = _find_cached_file(vid_id)
        if not cached_file or not os.path.exists(cached_file):
            continue

        # Check if query matches known query exactly
        if norm_query in queries:
            return {
                "vid_id": vid_id,
                "title": meta.get("title") or vid_id,
                "file_path": cached_file,
                "query": norm_query,
                "source": "local",
            }

        # Check title word overlap strictly
        title_clean = re.sub(r"[\[\(].*?[\]\)]", "", title).strip()
        title_words = set(title_clean.split())
        overlap = len(query_words & title_words) / max(len(query_words), 1)

        ratio = max(
            SequenceMatcher(None, norm_query, title_clean).ratio(),
            max([SequenceMatcher(None, norm_query, q).ratio() for q in queries], default=0.0)
        )

        # STRICT MATCH REQUIRED: Must share at least 60% of query words AND have high similarity
        if overlap >= 0.6 and ratio >= 0.55:
            score = (overlap * 0.5) + (ratio * 0.5)
            if score > best_score:
                best_score = score
                best = {
                    "vid_id": vid_id,
                    "title": meta.get("title") or vid_id,
                    "file_path": cached_file,
                    "query": norm_query,
                    "source": "local",
                }

    if best and best_score >= 0.6:
        print(f"[music] 🎯 Local cache matched: {best.get('title')} (score: {best_score:.2f})", flush=True)
        return best

    return None


def _record_play(track: Dict[str, Any]) -> None:
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


def _low_priority_prefix() -> List[str]:
    prefix: List[str] = []
    if shutil.which("ionice"):
        prefix.extend(["ionice", "-c2", "-n7"])
    if shutil.which("nice"):
        prefix.extend(["nice", "-n", "10"])
    return prefix


def _candidate_cookie_files() -> List[str]:
    candidates: List[str] = []
    env_file = os.getenv("YT_DLP_COOKIES_FILE", "").strip()
    if env_file:
        candidates.append(env_file)
    for fallback in (
        str(Path.home() / "Documents" / "rk-ai-assistant-main" / "youtube-cookies.txt"),
        str(Path.home() / "rk-ai-assistant-main" / "youtube-cookies.txt"),
        str(Path.cwd() / "youtube-cookies.txt"),
    ):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _ytdlp_auth_options() -> List[List[str]]:
    attempts: List[List[str]] = []

    # Use a real cookie file first when available.
    for cookie_file in _candidate_cookie_files():
        if cookie_file and os.path.exists(cookie_file):
            attempts.append(["--cookies", cookie_file])
            break

    # Use fast android/mweb client emulation
    attempts.append(["--extractor-args", "youtube:player_client=android,mweb"])
    return attempts


def _run_ytdlp_attempts(base_args: List[str], out_path: Optional[str] = None) -> List[List[str]]:
    attempts: List[List[str]] = []
    fast_flags = [
        "--no-part",
        "--retries",
        "2",
        "--socket-timeout",
        "8",
    ]
    for auth_args in _ytdlp_auth_options():
        cmd = _low_priority_prefix() + ["yt-dlp", "--quiet", "--no-warnings", "--force-ipv4"] + fast_flags + auth_args + base_args
        if out_path:
            cmd += ["-o", out_path]
        attempts.append(cmd)
    # Fast fallback without auth modifiers.
    attempts.append(_low_priority_prefix() + ["yt-dlp", "--quiet", "--no-warnings", "--force-ipv4"] + fast_flags + base_args + (["-o", out_path] if out_path else []))
    return attempts


def _spawn_player(file_path: str):
    if not file_path or not os.path.exists(file_path):
        # Allow direct stream URLs for fallback playback.
        if not (isinstance(file_path, str) and file_path.startswith(("http://", "https://"))):
            return None

    sink_name = ""
    try:
        sink_name = ensure_bluetooth_audio_route() or ""
    except Exception:
        sink_name = ""

    env = os.environ.copy()
    if sink_name:
        env["PULSE_SINK"] = sink_name

    is_url = isinstance(file_path, str) and file_path.startswith(("http://", "https://"))
    candidates: List[List[str]] = []
    if shutil.which("mpv"):
        candidates.append(["mpv", "--really-quiet", "--no-video", "--ao=pulse", file_path])
    if shutil.which("ffplay"):
        candidates.append(["ffplay", "-autoexit", "-nodisp", "-loglevel", "quiet", file_path])
    if shutil.which("vlc"):
        candidates.append(["vlc", "--play-and-exit", "--no-video", "--quiet", file_path])
    if shutil.which("cvlc"):
        candidates.append(["cvlc", "--play-and-exit", "--no-video", "--quiet", file_path])
    if not is_url and file_path.lower().endswith(".mp3") and shutil.which("mpg123"):
        candidates.append(["mpg123", "-o", "pulse", "-b", "32768", "--no-resync", "-q", file_path])

    for cmd in candidates:
        try:
            return subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
        except Exception as e:
            print(f"[music] Player launch failed for {cmd[0]}: {e}", flush=True)

    print("[music] No supported background audio player found.", flush=True)
    return None


def _probe_duration_seconds(file_path: str) -> Optional[float]:
    if not file_path or not os.path.exists(file_path):
        return None
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        res = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode == 0:
            text = (res.stdout or "").strip()
            if text:
                return float(text)
    except Exception:
        return None
    return None


def _search_youtube_match(norm_query: str) -> Optional[Dict[str, str]]:
    search_args = ["--get-title", "--get-id", f"ytsearch1:{norm_query}"]
    last_error = ""
    for cmd in _run_ytdlp_attempts(search_args):
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
            if len(lines) >= 2:
                return {"title": lines[0], "vid_id": lines[1]}
        last_error = (res.stderr or res.stdout or "").strip()
        if last_error:
            print(f"[music] yt-dlp search attempt failed: {last_error[-400:]}", flush=True)
    return None


def _download_track(track: Dict[str, Any], first_song: bool = False, announce_status: bool = True) -> Optional[Dict[str, Any]]:
    cache_dir = _songs_dir()
    title = track["title"]
    vid_id = track["vid_id"]
    safe_title = _safe_title(title)
    file_path_template = str(cache_dir / f"{safe_title} [{vid_id}].%(ext)s"[:255])
    safe_url = str(track.get("link") or "").strip() or f"https://www.youtube.com/watch?v={vid_id}"

    if first_song and announce_status:
        speak(f"Downloading {_announce_title(title)}")
    elif announce_status:
        speak(f"Downloading next {_announce_title(title)}")

    print(f"[music] ⬇️  Downloading... ({title})", flush=True)

    # Convert to mp3 when ffmpeg exists so mpg123 can play the cached file.
    base_args = ["--extract-audio", "--audio-format", "mp3", "--audio-quality", "0"] if shutil.which("ffmpeg") else ["-f", "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"]
    attempts: List[List[str]] = []
    for auth_args in _ytdlp_auth_options():
        attempts.append(_low_priority_prefix() + ["yt-dlp", "--quiet", "--no-warnings", "--force-ipv4"] + auth_args + base_args + ["-o", file_path_template, safe_url])
    attempts.append(_low_priority_prefix() + ["yt-dlp", "--quiet", "--no-warnings", "--force-ipv4"] + base_args + ["-o", file_path_template, safe_url])

    last_error = ""
    dl_res = None
    for cmd in attempts:
        dl_res = subprocess.run(cmd, capture_output=True, text=True)
        if dl_res.returncode == 0:
            break
        last_error = (dl_res.stderr or dl_res.stdout or "").strip()
        if last_error:
            print(f"[music] yt-dlp attempt failed: {last_error[-500:]}", flush=True)

    if not dl_res or dl_res.returncode != 0:
        if last_error:
            print(f"[music] yt-dlp download failed: {last_error[-500:]}", flush=True)
        return None

    exact_candidates = [
        cache_dir / f"{safe_title} [{vid_id}].mp3",
        cache_dir / f"{safe_title} [{vid_id}].m4a",
        cache_dir / f"{safe_title} [{vid_id}].webm",
        cache_dir / f"{safe_title} [{vid_id}].mp4",
        cache_dir / f"{safe_title} [{vid_id}].opus",
        cache_dir / f"{safe_title} [{vid_id}].ogg",
        cache_dir / f"{safe_title} [{vid_id}].mkv",
        cache_dir / f"{vid_id}.mp3",
        cache_dir / f"{vid_id}.m4a",
        cache_dir / f"{vid_id}.webm",
        cache_dir / f"{vid_id}.mp4",
        cache_dir / f"{vid_id}.opus",
        cache_dir / f"{vid_id}.ogg",
        cache_dir / f"{vid_id}.mkv",
    ]
    final_file = None
    for candidate in exact_candidates:
        if candidate.exists():
            final_file = str(candidate)
            break
    if not final_file:
        import glob
        for ext in _SUPPORTED_EXTS:
            matches = list(cache_dir.glob(f"*{glob.escape(vid_id)}*.{ext}"))
            if matches:
                final_file = str(matches[0])
                break

    if not final_file:
        print("[music] ❌ Download finished but file was not found.", flush=True)
        return None

    track = dict(track)
    track["file_path"] = final_file
    track["source_url"] = safe_url
    _append_query_to_index(vid_id, title, track.get("query", ""))
    return track


def _http_fast_search(norm_query: str) -> Optional[Dict[str, str]]:
    """Ultra-fast (<1s) lightweight search without spawning full yt-dlp search extractor."""
    try:
        import requests as _rq  # noqa: PLC0415
        resp = _rq.get(
            "https://www.youtube.com/results",
            params={"search_query": norm_query},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"},
            timeout=6,
        )
        if resp.status_code == 200:
            vids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', resp.text)
            titles = re.findall(r'"title":\{"runs":\[\{"text":"(.*?)"\}\]', resp.text)
            if vids:
                title = titles[0] if titles else norm_query
                return {"vid_id": vids[0], "title": title}
    except Exception as e:
        print(f"[music] Fast HTTP search failed: {e}", flush=True)
    return None


def _search_and_stream(norm_query: str) -> Optional[Dict[str, Any]]:
    """Fast search returning title, vid_id, and streaming URL."""
    # Step 1: Ultra-fast flat-playlist search via yt-dlp (<1.5s on Pi, no extraction overhead)
    flat_cmd = _low_priority_prefix() + [
        "yt-dlp",
        "--flat-playlist",
        "--quiet",
        "--no-warnings",
        "--force-ipv4",
        "--socket-timeout", "10",
        "--get-title",
        "--get-id",
        f"ytsearch1:{norm_query}",
    ]
    title = ""
    vid_id = ""
    try:
        res = subprocess.run(flat_cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0 and res.stdout.strip():
            lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
            if len(lines) >= 2:
                title = lines[0]
                vid_id = lines[1]
    except Exception as e:
        print(f"[music] Flat search failed: {e}", flush=True)

    # Fallback to HTTP search if flat search didn't get it
    if not vid_id:
        fast_match = _http_fast_search(norm_query)
        if fast_match:
            vid_id = fast_match["vid_id"]
            title = fast_match["title"]

    if vid_id:
        watch_url = f"https://www.youtube.com/watch?v={vid_id}"
        # Direct stream URL extraction for the single known video ID
        stream_cmd = _low_priority_prefix() + [
            "yt-dlp",
            "--quiet",
            "--no-warnings",
            "--force-ipv4",
            "--no-part",
            "--socket-timeout", "10",
            "-g",
            "-f", "bestaudio/best",
            watch_url,
        ]
        try:
            res = subprocess.run(stream_cmd, capture_output=True, text=True, timeout=20)
            if res.returncode == 0 and res.stdout.strip():
                stream_url = res.stdout.strip().splitlines()[0]
                return {
                    "title": title or norm_query,
                    "vid_id": vid_id,
                    "source_url": stream_url,
                }
        except Exception as e:
            print(f"[music] Stream URL resolution failed: {e}", flush=True)

        return {
            "title": title or norm_query,
            "vid_id": vid_id,
            "source_url": watch_url,
        }

    return None


def _download_track_bg(track: Dict[str, Any]):
    """Download and cache track in the background without holding up playback."""
    try:
        _download_track(track, first_song=False, announce_status=False)
    except Exception as e:
        print(f"[music] Background download error: {e}", flush=True)


def _resolve_track(norm_query: str, announce: bool = True) -> Optional[Dict[str, Any]]:
    if not norm_query:
        return None

    local_track = _resolve_local_track(norm_query)
    if local_track:
        return local_track

    if announce:
        speak(f"Searching for song {norm_query}")
    _set_music_state("searching")

    match = _search_and_stream(norm_query)
    if not match:
        _set_music_state("idle")
        return None

    title = match["title"]
    vid_id = match["vid_id"]
    source_url = match.get("source_url")
    print(f"[music] ✓ Found: {title} ({vid_id})", flush=True)

    cached_file = _find_cached_file(vid_id)
    track = {
        "vid_id": vid_id,
        "title": title,
        "file_path": cached_file or source_url,
        "source_url": source_url,
        "query": norm_query,
        "source": "youtube",
    }
    _append_query_to_index(vid_id, title, norm_query)

    if cached_file and os.path.exists(cached_file):
        track["file_path"] = cached_file
        return track

    # Check user preference from mobile app: Default is pure direct stream (fastest & no stutter).
    # If the user explicitly toggled "Download Songs" in the app, download in background.
    try:
        from .settings_sync import is_music_download_enabled  # noqa: PLC0415
        if is_music_download_enabled() and source_url:
            threading.Thread(target=_download_track_bg, args=(track,), daemon=True).start()
    except Exception:
        pass

    if source_url:
        return track

    # If no direct stream url, return None
    _set_music_state("idle")
    return None


def _music_done_watcher(proc, generation: int):
    global current_player, current_track_info, _music_state
    try:
        proc.wait()
    except Exception:
        return
    with _player_lock:
        if current_player is proc:
            current_player = None
            current_track_info = None
            _set_music_state("idle")


def play_music(query: str, announce_status: bool = True):
    global current_player, current_track_info, last_played_query

    norm_query = _clean_query(query)
    print(f"[music] 🧹 Cleaned Query: '{norm_query}' (Original: '{query}')", flush=True)

    if _has_stop_command(norm_query):
        stop_music()
        return None

    # Check local cached songs first
    local_track = _resolve_local_track(norm_query)
    if not local_track and not shutil.which("yt-dlp"):
        print("[music] Install yt-dlp first for YouTube search/playback.", flush=True)
        if announce_status:
            speak("Please install yt-dlp on your device to play online music.")
        return None

    if current_player and current_player.poll() is None:
        stop_music()

    last_played_query = query
    track = local_track or _resolve_track(norm_query, announce=announce_status)
    if not track:
        if announce_status:
            speak("I couldn't find that song.")
        return None

    speak_title = _announce_title(track.get("title", "music"))
    print(f"[music] ▶️  Now playing {track.get('title')}", flush=True)

    play_ref = track.get("file_path") or track.get("source_url")
    # Announce cleanly before spawning music player to avoid Bluetooth audio channel choking
    if announce_status and current_track_info is None:
        speak(f"Now playing {speak_title}")

    proc = _spawn_player(str(play_ref or ""))
    if not proc:
        if announce_status:
            speak("I couldn't play that song.")
        return None

    current_player = proc
    current_track_info = dict(track)
    _record_play(track)
    _set_music_state("playing")
    threading.Thread(target=_music_done_watcher, args=(proc, 0), daemon=True).start()
    return proc


def stop_music():
    global current_player, current_track_info
    try:
        if current_player and current_player.poll() is None:
            current_player.terminate()
            try:
                current_player.wait(timeout=2)
            except Exception:
                pass
    except Exception:
        pass

    for proc_name in ("vlc", "cvlc", "ffplay", "mpv", "mpg123"):
        try:
            subprocess.run(["pkill", "-9", proc_name], stderr=subprocess.DEVNULL)
        except Exception:
            pass

    current_player = None
    current_track_info = None
    _set_music_state("idle")
    print("[music] ⏹️  Stopped", flush=True)


def pause_music():
    if current_player and current_player.poll() is None:
        try:
            current_player.send_signal(signal.SIGSTOP)
            print("[music] ⏸️  Paused", flush=True)
        except Exception as e:
            print(f"[music] Pause error: {e}", flush=True)


def unpause_music():
    if current_player and current_player.poll() is None:
        try:
            current_player.send_signal(signal.SIGCONT)
            print("[music] ▶️  Resumed", flush=True)
        except Exception as e:
            print(f"[music] Resume error: {e}", flush=True)


def search_local_and_play(norm_query: str):
    track = _resolve_local_track(_clean_query(norm_query))
    if not track:
        return None
    return _spawn_player(track["file_path"])


def search_youtube_and_play(norm_query: str):
    return play_music(norm_query)


def sync_music_index():
    try:
        cache_dir = _songs_dir()
        index = _load_index()
        files: List[Path] = []
        for ext in _SUPPORTED_EXTS:
            files.extend(list(cache_dir.glob(f"*.{ext}")))
        if not files:
            return

        updated = False
        print(f"[music] 🔄 Syncing music index ({len(files)} files)...", flush=True)
        for f in files:
            vid_id = _extract_vid_id(f.name)
            if not vid_id:
                continue
            if vid_id in index:
                continue

            try:
                cmd = ["yt-dlp", "--force-ipv4", "--get-title", f"https://www.youtube.com/watch?v={vid_id}"]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0 and res.stdout.strip():
                    title = res.stdout.strip().splitlines()[0].strip()
                    index[vid_id] = {"title": title, "queries": []}
                    updated = True
                    print(f"[music] ✓ Added to index: {title}", flush=True)
            except Exception as e:
                print(f"[music] Error fetching title for {vid_id}: {e}", flush=True)

        if updated:
            _save_index(index)
            print("[music] ✅ Index sync complete.", flush=True)
    except Exception as e:
        print(f"[music] Index sync error: {e}", flush=True)


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

    def _candidate_sort(path_obj: Path):
        vid_id = _extract_vid_id(path_obj.name) or path_obj.stem
        entry = stats.get(vid_id, {})
        return (
            0 if int(entry.get("play_count", 0)) <= 1 else 1,
            int(entry.get("play_count", 0)),
            int(entry.get("last_played_at", 0)),
        )

    for path_obj in sorted(files, key=_candidate_sort):
        if str(path_obj) == current_file:
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
