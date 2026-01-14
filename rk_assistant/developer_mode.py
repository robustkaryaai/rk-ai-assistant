"""
Developer Mode for RK Assistant.
Interactive diagnostic tool for testing system components.
Run with: python3 -m rk_assistant.developer_mode
"""

import os
import sys
import time
import subprocess
import threading
from getpass import getpass
from .config import GEMINI_API_KEY, BACKEND_BASE_URL, SLUG_FILE
from .gemini_client import test_gemini_connection
from .networking import check_network_health, is_online
from .audio_utils_simple import speak
import sounddevice as sd
import numpy as np
import wave

# Default Password (should be moved to env for production)
DEV_PASSWORD = os.getenv("DEV_PASSWORD", "rkadmin")

def print_header(text):
    print(f"\n{'='*40}")
    print(f"  {text}")
    print(f"{'='*40}\n")

def check_auth():
    print_header("🔐 DEVELOPER MODE AUTHENTICATION")
    attempts = 0
    while attempts < 3:
        pwd = getpass("Enter Developer Password: ")
        if pwd == DEV_PASSWORD:
            print("✅ Access Granted.")
            return True
        else:
            print("❌ Access Denied.")
            attempts += 1
    return False

def test_network():
    print_header("1. NETWORK DIAGNOSTICS 📶")
    print("[*] Checking internet connectivity...")
    if is_online():
        print("✅ Internet: ONLINE")
    else:
        print("❌ Internet: OFFLINE")
    
    print("[*] Running network health check...")
    from .networking import check_network_health
    check_network_health()

def test_gemini():
    print_header("2. GEMINI AI DIAGNOSTICS 🧠")
    print(f"[*] API Key Present: {'Yes' if GEMINI_API_KEY else 'No'}")
    
    if GEMINI_API_KEY:
        print("[*] Testing API connection (Saying 'Hello')...")
        start = time.time()
        result = test_gemini_connection(GEMINI_API_KEY)
        duration = time.time() - start
        
        if result:
            print(f"✅ Gemini Connection: SUCCESS ({duration:.2f}s)")
        else:
            print("❌ Gemini Connection: FAILED")
    else:
        print("❌ Skipping test (No API Key)")

def test_backend():
    print_header("3. BACKEND DIAGNOSTICS ☁️")
    print(f"[*] Backend URL: {BACKEND_BASE_URL}")
    print("[*] Pinging backend...")
    
    import requests
    try:
        # Just check if we can reach the base URL or root
        # Since actual endpoints need slugs, we'll try a simple health check if exists, 
        # or just fetch google.com if backend doesn't have a root get.
        # Actually let's try to fetch the device check endpoint with a dummy slug
        url = f"{BACKEND_BASE_URL.replace('/api', '')}/" # Root
        resp = requests.get(url, timeout=5)
        print(f"✅ Backend Reachable (Status: {resp.status_code})")
    except Exception as e:
        print(f"❌ Backend Unreachable: {e}")

def test_audio_output():
    print_header("4. AUDIO OUTPUT TEST 🔊")
    print("[*] Playing test tone...")
    try:
        # Simple beep using sox or aplay if available, or just speak
        speak("Audio output test initiated.")
        print("✅ TTS Output: SENT (Did you hear it?)")
    except Exception as e:
        print(f"❌ Audio Output Error: {e}")

def test_audio_input():
    print_header("5. MICROPHONE TEST 🎤")
    print("[*] Recording 3 seconds... SPEAK NOW!")
    try:
        fs = 16000  # Sample rate
        seconds = 3
        
        # Record
        myrecording = sd.rec(int(seconds * fs), samplerate=fs, channels=1, dtype='int16')
        sd.wait()  # Wait until recording is finished
        print("[*] Recording finished.")
        
        print("[*] Playing back recording...")
        sd.play(myrecording, fs)
        sd.wait()
        print("✅ Info: Playback complete. (Did you hear yourself?)")
        
    except Exception as e:
        print(f"❌ Microphone Error: {e}")
        print("(Note: This requires 'sounddevice' and 'portaudio' installed)")

def test_music_dependencies():
    print_header("6. MUSIC SYSTEM CHECK 🎵")
    
    # Check yt-dlp
    yt_check = subprocess.run(["which", "yt-dlp"], capture_output=True, text=True)
    if yt_check.returncode == 0:
        print(f"✅ yt-dlp: INSTALLED ({yt_check.stdout.strip()})")
    else:
        print("❌ yt-dlp: NOT FOUND")

    # Check ffmpeg
    ff_check = subprocess.run(["which", "ffmpeg"], capture_output=True, text=True)
    if ff_check.returncode == 0:
        print(f"✅ ffmpeg: INSTALLED ({ff_check.stdout.strip()})")
    else:
        print("❌ ffmpeg: NOT FOUND")

def main():
    if not check_auth():
        sys.exit(1)
        
    print("\n🚀 STARTING SYSTEM DIAGNOSTICS...\n")
    
    test_network()
    time.sleep(1)
    
    test_gemini()
    time.sleep(1)
    
    test_backend()
    time.sleep(1)
    
    test_music_dependencies()
    time.sleep(1)
    
    test_audio_output()
    time.sleep(1)
    
    test_audio_input()
    
    print_header("✨ DIAGNOSTICS COMPLETE ✨")

if __name__ == "__main__":
    main()
