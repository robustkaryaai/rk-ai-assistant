#!/usr/bin/env python3
"""
download_model.py — Downloads Qwen2.5-0.5B Q4_K_M GGUF for offline use on Pi Zero W.
Run once on the Pi: python3 v2/llm/download_model.py
"""

import os
import sys
import urllib.request
import ssl

MODEL_URL  = "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
MODEL_PATH = os.path.expanduser("~/models/qwen.gguf")
EXPECTED_MB = 300  # approximate

def download():
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)

    if os.path.isfile(MODEL_PATH):
        mb = os.path.getsize(MODEL_PATH) / 1024 / 1024
        if mb > 50:
            print(f"✅ Model already downloaded ({mb:.0f}MB) at {MODEL_PATH}")
            return
        else:
            print(f"⚠️  Found incomplete file ({mb:.1f}MB), re-downloading...")

    print(f"📥 Downloading Qwen2.5-0.5B Q4_K_M (~{EXPECTED_MB}MB)...")
    print(f"   Destination: {MODEL_PATH}")
    print(f"   Note: This will take several minutes on Pi Zero W's connection.\n")

    # Use unverified SSL context (avoids cert issues on older Pi OS)
    ctx = ssl._create_unverified_context()

    def progress(count, block_size, total_size):
        if total_size <= 0:
            return
        pct  = min(100, count * block_size * 100 // total_size)
        done = count * block_size / 1024 / 1024
        total = total_size / 1024 / 1024
        bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
        sys.stdout.write(f"\r   [{bar}] {pct}% — {done:.1f}/{total:.1f} MB")
        sys.stdout.flush()

    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
    urllib.request.install_opener(opener)
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH, progress)

    print()
    mb = os.path.getsize(MODEL_PATH) / 1024 / 1024
    print(f"\n✅ Download complete! {mb:.1f}MB saved to {MODEL_PATH}")
    print("   You can now run: python3 v2/main.py")

if __name__ == "__main__":
    download()
