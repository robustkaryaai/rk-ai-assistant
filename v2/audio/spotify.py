"""
Spotify Integration Gateway for RK AI Assistant V2.
Handles Spotify playback resolution:
1. If user connects Spotify account / token via App, plays Spotify track/playlist.
2. If token is present, triggers Spotify Connect web API playback.
3. Queries high-speed cloud Spotify bridge (/device/:slug/spotify/resolve).
4. Smooth fallback to direct stream so music always plays instantly.
"""

import os
import ssl
import json
import urllib.request
import requests
from pathlib import Path
from typing import Optional, Dict, Any

try:
    from config import BASE_DIR
except ImportError:
    from v2.config import BASE_DIR


class SpotifyManager:
    def __init__(self, token_file: Optional[str] = None):
        self.access_token: Optional[str] = None
        self.is_connected: bool = False
        self.token_file = token_file

    def set_token(self, token: str):
        self.access_token = token
        self.is_connected = bool(token)
        print("🟢 [SPOTIFY] Spotify account connected.", flush=True)

    def play_track_or_query(self, query: str, streamer=None, player=None) -> bool:
        """
        Play music via Spotify.
        1. Local Spotify Connect if token is in memory.
        2. Backend /device/:slug/spotify/resolve for instant cloud Connect or stream bridge.
        """
        # 1. Direct local Spotify Connect API
        if self.is_connected and self.access_token:
            headers = {"Authorization": f"Bearer {self.access_token}"}
            try:
                search_url = "https://api.spotify.com/v1/search"
                params = {"q": query, "type": "track", "limit": 1}
                resp = requests.get(search_url, headers=headers, params=params, timeout=4)
                if resp.status_code == 200:
                    items = resp.json().get("tracks", {}).get("items", [])
                    if items:
                        track = items[0]
                        track_uri = track.get("uri")
                        play_url = "https://api.spotify.com/v1/me/player/play"
                        play_resp = requests.put(play_url, headers=headers, json={"uris": [track_uri]}, timeout=4)
                        if play_resp.status_code in (200, 204):
                            print(f"🎵 [SPOTIFY] Playing via Spotify Connect: {track.get('name')}", flush=True)
                            return True
            except Exception as e:
                print(f"[spotify] Local Spotify API notice: {e}", flush=True)

        # 2. Cloud Server-side Spotify Resolution
        slug_file = BASE_DIR / "slug.txt"
        slug = slug_file.read_text().strip() if slug_file.exists() else "123456789"
        backend_url = f"https://rk-ai-backend.onrender.com/device/{slug}/spotify/resolve"

        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            payload = json.dumps({"query": query}).encode()
            headers = {
                "Content-Type": "application/json",
                "X-Device-Slug": slug
            }
            req = urllib.request.Request(backend_url, data=payload, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=6.0) as resp:
                res_data = json.loads(resp.read().decode())
                if res_data.get("connect_active"):
                    print(f"🎵 [SPOTIFY] Cloud triggered Spotify Connect: '{res_data.get('title')}'", flush=True)
                    return True
                stream_url = res_data.get("stream_url")
                if stream_url and player:
                    print(f"🎵 [SPOTIFY] Playing track '{res_data.get('title')}' via audio stream...", flush=True)
                    player.play_url_or_file(stream_url)
                    return True
        except Exception as e:
            print(f"[spotify] Cloud Spotify resolve notice: {e}", flush=True)

        # 3. Stream resolution fallback
        if streamer and player:
            url = streamer.get_audio_stream_url(query)
            if url:
                player.play_url_or_file(url)
                return True
        return False
