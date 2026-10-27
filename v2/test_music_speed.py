#!/usr/bin/env python3
import time
from audio.streamer import LocalMusicStreamer

q = "shape of you"
print(f"⏱️ Testing music resolution speed on this device for: '{q}'...")
t0 = time.time()
url = LocalMusicStreamer.get_audio_stream_url(q)
elapsed = time.time() - t0

if url:
    print(f"\n✅ SUCCESS: Resolved in {elapsed:.2f} seconds!")
    print(f"🔗 Stream URL: {url[:70]}...")
else:
    print(f"\n❌ FAILED to resolve in {elapsed:.2f} seconds.")
