#!/usr/bin/env python3
"""
RK AI Assistant — Interactive Music Test Tool
Asks for a song query, resolves via backend/yt-dlp, plays on Pi speaker.
Usage: python3 v2/test_music.py
"""
import sys
import ssl
import json
import time
import shutil
import subprocess
import threading
import urllib.request
import urllib.parse
from pathlib import Path


# Add v2 to path so imports work
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

print("=" * 60)
print("🎵  RK AI Assistant — Music Resolution & Playback Test")
print("=" * 60)

# ── Load config ────────────────────────────────────────────────
try:
    from config import BACKEND_BASE_URL, DEVICE_SLUG
except Exception as e:
    print(f"⚠️  Could not load config: {e}")
    BACKEND_BASE_URL = "https://rk-ai-backend.onrender.com"
    DEVICE_SLUG = "123456789"

print(f"🌐 Backend: {BACKEND_BASE_URL}")
print(f"🔑 Slug:    {DEVICE_SLUG}")

# ── Get query from user ────────────────────────────────────────
print()
query = input("🎤 Enter song name / query: ").strip()
if not query:
    print("❌ No query entered. Exiting.")
    sys.exit(1)

print(f"\n🔍 Resolving: '{query}' ...")

# ── Try backend resolution first ──────────────────────────────


stream_url = None

print("\n[Step 1/3] Asking backend to resolve stream URL...")
try:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    backend_resolve = f"{BACKEND_BASE_URL}/device/{DEVICE_SLUG}/music/resolve"
    payload = json.dumps({"query": query}).encode()
    req = urllib.request.Request(
        backend_resolve,
        data=payload,
        headers={"Content-Type": "application/json", "X-Device-Slug": DEVICE_SLUG}
    )
    t0 = time.time()
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    elapsed = time.time() - t0
    print(f"  ✅ Backend responded in {elapsed:.1f}s")
    print(f"  📋 Raw response: {data}")

    candidate = data.get("stream_url") or data.get("link") or data.get("url")
    title = data.get("title", "")
    if candidate:
        print(f"  🎵 Backend resolved: '{title}' → {candidate[:80]}...")
        # If it's a direct non-YouTube CDN URL, use it straight away
        if not ("youtube.com" in candidate or "youtu.be" in candidate):
            stream_url = candidate
            print(f"  ✅ Direct CDN stream — no extraction needed.")
        else:
            print(f"  ℹ️  Got YouTube URL — will extract audio stream next.")
            yt_url = candidate
    else:
        yt_url = f"https://www.youtube.com/results?search_query={query}"
        print(f"  ⚠️  Backend gave no stream URL. Will search YouTube directly.")
except Exception as e:
    print(f"  ⚠️  Backend resolve failed: {e}")
    yt_url = query  # fall back to query string for yt-dlp ytsearch

# ── Fast Mac LAN Resolver (1.5s resolution) ───────────────────
if not stream_url and yt_url:
    print("\n[Step 1.5] Checking Fast Mac LAN Resolver (192.168.1.10:7070)...")
    for mac_ip in ["192.168.1.10", "192.168.1.5"]:
        try:
            mac_url = f"http://{mac_ip}:7070"
            payload = json.dumps({"query": yt_url}).encode()
            req = urllib.request.Request(mac_url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                m_data = json.loads(resp.read().decode())
                if m_data.get("ok") and m_data.get("stream_url"):
                    stream_url = m_data["stream_url"]
                    print(f"  ⚡ Resolved in {m_data.get('elapsed')}s via Mac LAN server!")
                    break
        except Exception:
            pass

# ── yt-dlp extraction (fallback on Pi if Mac not reachable) ───
if not stream_url:
    print("\n[Step 2/3] Extracting audio stream via Pi local yt-dlp...")
    if not shutil.which("yt-dlp"):
        print("  ❌ yt-dlp not found! Install: pip3 install yt-dlp --break-system-packages")
        sys.exit(1)

    # If yt_url is not a proper URL yet, use ytsearch
    if not yt_url.startswith("http"):
        yt_url = f"ytsearch1:{yt_url}"

    cmd = [
        "yt-dlp",
        "-f", "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
        "-g",
        "--no-playlist",
        "--no-warnings",
        "--geo-bypass",
        "--socket-timeout", "10",
        "--extractor-retries", "3",
        yt_url,
    ]
    print(f"  Running: {' '.join(cmd[:6])} ... {yt_url[:60]}")
    t0 = time.time()
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=45)
        elapsed = time.time() - t0
        print(f"  yt-dlp finished in {elapsed:.1f}s (exit code {res.returncode})")
        if res.stderr.strip():
            print(f"  yt-dlp stderr: {res.stderr.strip()[:300]}")
        for line in res.stdout.strip().splitlines():
            line = line.strip()
            if line.startswith("http"):
                stream_url = line
                print(f"  ✅ Audio stream extracted: {stream_url[:80]}...")
                break
        if not stream_url:
            print("  ❌ yt-dlp returned no stream URL.")
    except subprocess.TimeoutExpired:
        print("  ❌ yt-dlp timed out (45s).")
    except Exception as e:
        print(f"  ❌ yt-dlp error: {e}")
else:
    print("\n[Step 2/3] Skipped yt-dlp (direct stream from backend).")

# ── Playback ───────────────────────────────────────────────────
print("\n[Step 3/3] Playing audio...")
if not stream_url:
    print("❌ No stream URL available. Cannot play.")
    sys.exit(1)

print(f"  🔊 Stream URL: {stream_url[:100]}...")

played = False
for player in ["ffplay", "mpv", "cvlc", "mpg123"]:
    if shutil.which(player):
        try:
            if player == "ffplay":
                cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-rtbufsize", "10M", stream_url]
            elif player == "mpv":
                cmd = ["mpv", "--no-video", "--volume=100", "--ytdl=no", "--ao=pulse,alsa",
                       "--audio-buffer=1.0", "--cache=yes", "--cache-secs=30",
                       "--really-quiet", stream_url]
            elif player == "cvlc":
                cmd = ["cvlc", "--play-and-exit", "--no-video", "--quiet", stream_url]
            elif player == "mpg123":
                cmd = ["mpg123", "-o", "pulse", "-q", stream_url]

            print(f"  🎵 Launching {player}... (Ctrl+C to stop)")
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proc.wait()
            played = True
            break
        except KeyboardInterrupt:
            proc.terminate()
            print("\n  ⏹️  Stopped by user.")
            played = True
            break
        except Exception as e:
            print(f"  ⚠️  {player} failed: {e}")

if not played:
    print("❌ No supported audio player found (ffplay / mpv / cvlc / mpg123).")

print("\nDone!")
