"""
Spotify Integration Gateway for RK AI Assistant V2.
Handles Spotify playback resolution:
1. If user connects Spotify account / token via App, plays Spotify track/playlist.
2. If token is present, can trigger Spotify Connect web API playback.
3. If Spotify search query is requested without token, smoothly bridges track title to high-quality audio stream.
"""

import os
import requests
from typing import Optional, Dict, Any

class SpotifyManager:
    def __init__(self, token_file: Optional[str] = None):
        self.access_token: Optional[str] = None
        self.is_connected: bool = False
        self.token_file = token_file

    def set_token(self, token: str):
        self.access_token = token
        self.is_connected = bool(token)
        print("🟢 [SPOTIFY] Spotify account connected.")

    def play_track_or_query(self, query: str, streamer=None, player=None) -> bool:
        """
        Play music via Spotify.
        If user has active Spotify Connect session, sends play command to Spotify API.
        Otherwise falls back to streamer with Spotify query precision.
        """
        if self.is_connected and self.access_token:
            headers = {"Authorization": f"Bearer {self.access_token}"}
            try:
                # Search Spotify API
                search_url = "https://api.spotify.com/v1/search"
                params = {"q": query, "type": "track", "limit": 1}
                resp = requests.get(search_url, headers=headers, params=params, timeout=5)
                if resp.status_code == 200:
                    items = resp.json().get("tracks", {}).get("items", [])
                    if items:
                        track = items[0]
                        track_uri = track.get("uri")
                        # Trigger Spotify Connect play on active device
                        play_url = "https://api.spotify.com/v1/me/player/play"
                        play_resp = requests.put(play_url, headers=headers, json={"uris": [track_uri]}, timeout=5)
                        if play_resp.status_code in (200, 204):
                            print(f"🎵 [SPOTIFY] Playing via Spotify Connect: {track.get('name')}")
                            return True
            except Exception as e:
                print(f"[spotify] Spotify API error: {e}")

        # Stream resolution fallback
        if streamer and player:
            url = streamer.get_audio_stream_url(query)
            if url:
                player.play_url_or_file(url)
                return True
        return False
