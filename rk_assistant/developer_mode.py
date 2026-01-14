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
        
        print("[*] Playing back recording (with 5x volume boost)...")
        sd.play(myrecording * 5, fs)
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
        print("   👉 Fix: Run 'pip install yt-dlp' on the Pi.")

    # Check ffmpeg
    ff_check = subprocess.run(["which", "ffmpeg"], capture_output=True, text=True)
    if ff_check.returncode == 0:
        print(f"✅ ffmpeg: INSTALLED ({ff_check.stdout.strip()})")
    else:
        print("❌ ffmpeg: NOT FOUND")

def test_intent_classification():
    print_header("7. INTENT CLASSIFICATION TEST 🎯")
    print("[*] Testing Gemini's ability to classify intents...")
    
    if not GEMINI_API_KEY:
        print("❌ Skipped (No API Key)")
        return
    
    try:
        from .gemini_client import classify_intent
        
        test_query = "What time is it?"
        print(f"[*] Query: '{test_query}'")
        
        result = classify_intent(test_query, api_key=GEMINI_API_KEY)
        
        if result and isinstance(result, list) and len(result) > 0:
            intent_name = result[0].get("intent", "unknown")
            print(f"✅ Classification Success: '{intent_name}'")
        else:
            print("❌ Classification Failed: No valid intent returned")
            
    except Exception as e:
        print(f"❌ Classification Error: {e}")

def test_time_intent():
    print_header("8. TIME INTENT TEST 🕐")
    print("[*] Testing local time retrieval...")
    
    try:
        from .local_handlers import handle_time
        
        time_str = handle_time()
        if time_str:
            print(f"✅ Time Retrieved: {time_str}")
        else:
            print("❌ Time handler returned empty")
            
    except Exception as e:
        print(f"❌ Time Error: {e}")

def test_volume_control():
    print_header("9. VOLUME CONTROL TEST 🔊")
    print("[*] Testing volume adjustment...")
    
    try:
        from .audio_utils import set_volume, get_current_volume
        
        # Get current volume
        current = get_current_volume()
        print(f"[*] Current Volume: {current}%")
        
        # Test setting volume
        set_volume(60)
        new_vol = get_current_volume()
        
        if new_vol == 60:
            print("✅ Volume Control: WORKING")
            # Restore original volume
            set_volume(current)
        else:
            print(f"⚠️ Volume set to 60 but got {new_vol}")
            
    except Exception as e:
        print(f"❌ Volume Error: {e}")

def test_bluetooth_status():
    print_header("10. BLUETOOTH STATUS TEST 📡")
    print("[*] Checking Bluetooth speaker connection...")
    
    try:
        from .config import BLUETOOTH_SPEAKER_MAC
        
        # Check connection via bluetoothctl
        result = subprocess.run(
            ["bluetoothctl", "info", BLUETOOTH_SPEAKER_MAC],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if "Connected: yes" in result.stdout:
            print(f"✅ Speaker Connected: {BLUETOOTH_SPEAKER_MAC}")
        else:
            print(f"❌ Speaker Disconnected: {BLUETOOTH_SPEAKER_MAC}")
            
    except Exception as e:
        print(f"❌ Bluetooth Error: {e}")

def test_music_search():
    print_header("11. MUSIC SEARCH TEST 🎵")
    print("[*] Testing music search pipeline...")
    
    try:
        # Check if yt-dlp is available first
        yt_check = subprocess.run(["which", "yt-dlp"], capture_output=True, text=True)
        if yt_check.returncode != 0:
            print("⚠️ Skipped (yt-dlp not installed)")
            return
        
        # Dry-run search (don't download)
        test_song = "Sandese aate hai"
        print(f"[*] Searching for: '{test_song}'")
        
        result = subprocess.run(
            ["yt-dlp", "--get-title", f"ytsearch1:{test_song}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0 and result.stdout.strip():
            print(f"✅ Music Search: WORKING (Found: {result.stdout.strip()[:50]}...)")
        else:
            print("❌ Music Search: FAILED")
            
    except Exception as e:
        print(f"❌ Music Search Error: {e}")

def test_backend_integration():
    print_header("12. BACKEND INTEGRATION TEST ☁️")
    print("[*] Testing backend communication...")
    
    try:
        from .networking import post_text_to_backend
        
        # Read slug
        slug_path = Path(SLUG_FILE)
        if not slug_path.exists():
            print("⚠️ Skipped (No slug file)")
            return
        
        slug = slug_path.read_text().strip().split('\n')[0]
        print(f"[*] Using Slug: {slug}")
        
        # Send test message
        response = post_text_to_backend("Test from developer mode", slug)
        
        if response and not response.get("error"):
            print("✅ Backend Communication: SUCCESS")
        else:
            print(f"⚠️ Backend Response: {response}")
            
    except Exception as e:
        print(f"❌ Backend Error: {e}")

def test_conversational_ai():
    print_header("13. CONVERSATIONAL AI TEST 💬")
    print("[*] Testing Gemini chat response...")
    
    if not GEMINI_API_KEY:
        print("❌ Skipped (No API Key)")
        return
    
    try:
        from .gemini_client import get_conversational_response
        
        test_prompt = "Say hello"
        print(f"[*] Prompt: '{test_prompt}'")
        
        response = get_conversational_response(test_prompt, api_key=GEMINI_API_KEY)
        
        if response and len(response) > 0 and "trouble" not in response.lower():
            print(f"✅ AI Response: {response[:80]}...")
        else:
            print(f"❌ AI Response Failed: {response}")
            
    except Exception as e:
        print(f"❌ Conversational AI Error: {e}")

def main():
    if not check_auth():
        sys.exit(1)
        
    print("\n🚀 STARTING SYSTEM DIAGNOSTICS...\n")
    
    tests = [
        test_network,
        test_gemini,
        test_backend,
        test_music_dependencies,
        test_audio_output,
        test_audio_input,
        test_intent_classification,
        test_time_intent,
        test_volume_control,
        test_bluetooth_status,
        test_music_search,
        test_backend_integration,
        test_conversational_ai
    ]
    
    for test in tests:
        start_time = time.time()
        test()
        duration = time.time() - start_time
        print(f"⏱️  {test.__name__} completed in {duration:.4f}s")
        time.sleep(1)
    
    print_header("✨ DIAGNOSTICS COMPLETE ✨")

if __name__ == "__main__":
    main()
