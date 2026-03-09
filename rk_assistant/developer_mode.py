"""
RK AI - Developer Mode & Testing Suite

This script provides an interactive CLI to test every component of the 
RK AI system in complete isolation. You can verify network status, test 
hardware microphones with WebRTC VAD, test TTS engines, query Gemini, 
route offline commands, and interact with the experimental offline SmolLM model.
"""

import os
import sys
import time
from pathlib import Path

# Ensure package context so relative imports work
if __name__ == "__main__" and __package__ is None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    sys.path.insert(0, parent_dir)
    __package__ = "rk_assistant"

from rk_assistant import audio_utils
from rk_assistant.networking import is_online, read_slug, fetch_slug_from_env
from rk_assistant.config import (
    LAST_AUDIO, BACKEND_BASE_URL, GEMINI_API_KEY, 
    GEMINI_API_KEY_BACKUP, STT_ENGINE, MIC_DEVICE_INDEX
)
from rk_assistant.offline_commands import match_offline_command, process_offline_command
from rk_assistant.gemini_client import generate_response
from rk_assistant.weather_news import fetch_weather, fetch_news

def print_header(title: str):
    print("\n" + "=" * 60)
    print(f" DEVELOPER MODE: {title}")
    print("=" * 60)

def _get_smollm_response(prompt: str) -> str:
    """Test hook for the 135-parameter offline LLM."""
    try:
        from llama_cpp import Llama
    except ImportError:
        return "\n❌ [ERROR] llama-cpp-python not installed.\n   Run: pip install llama-cpp-python\n   Note: Building this on Pi Zero takes a very long time."
        
    model_path = os.path.join(current_dir, "model", "SmolLM-135M-Instruct-Q4_K_M.gguf")
    if not os.path.exists(model_path):
        return f"\n❌ [ERROR] Model not found at {model_path}.\n   Run: wget https://huggingface.co/lmstudio-community/SmolLM-135M-Instruct-GGUF/resolve/main/SmolLM-135M-Instruct-Q4_K_M.gguf -P {os.path.join(current_dir, 'model')}"
        
    try:
        print(f"\n[SmolLM] Loading 135M parameter model into memory...")
        start_time = time.time()
        llm = Llama(model_path=model_path, n_ctx=256, verbose=False)
        print(f"[SmolLM] Loaded in {time.time() - start_time:.2f}s")
        
        print(f"\n[SmolLM] Generating response (Watch token speed)...")
        gen_start = time.time()
        output = llm(
            f"Question: {prompt}\nAnswer:",
            max_tokens=64, 
            stop=["Question:", "\n"],
            echo=False
        )
        duration = time.time() - gen_start
        text = output['choices'][0]['text'].strip()
        tokens = output['usage']['completion_tokens']
        
        print(f"\n[SmolLM Stats] Generated {tokens} tokens in {duration:.2f}s ({tokens/duration:.2f} t/s)")
        return text
    except Exception as e:
        return f"\n❌ [SmolLM ERROR]: {e}"

def test_network_and_config():
    print_header("1. Network & Configuration")
    print("Pinging 8.8.8.8 to verify internet connectivity...")
    online = is_online()
    print(f"\nInternet Status: {'✅ ONLINE' if online else '❌ OFFLINE'}")
    
    slug, _ = read_slug()
    if not slug:
        slug = fetch_slug_from_env()
    print(f"Device Slug:     {slug if slug else '❌ NOT FOUND'}")
    
    print(f"Backend Server:  {BACKEND_BASE_URL}")
    print(f"STT Engine:      {STT_ENGINE}")
    print(f"Gemini Key 1:    {'✅ CONFIGURED' if GEMINI_API_KEY else '❌ MISSING'}")
    print(f"Gemini Key 2:    {'✅ CONFIGURED' if GEMINI_API_KEY_BACKUP else '❌ MISSING'}")
    input("\nPress Enter to return to menu...")

def test_microphone_and_vad():
    print_header("2. Microphone & WebRTC VAD")
    print(f"Configured Hardware Device Index: {MIC_DEVICE_INDEX}")
    print("\nTesting recording loop with integrated WebRTC noise suppression...")
    print(" 1. Please stay completely silent for 2 seconds.")
    print(" 2. Then speak a sentence clearly.")
    print(" 3. Then stay silent again to trigger the end of the recording.")
    input("\n[Press Enter to begin recording...]")
    
    start = time.time()
    audio_path = audio_utils.record_until_silence(out_path=LAST_AUDIO, silence_duration=1.5)
    
    if not audio_path or not os.path.exists(audio_path):
        print("\n❌ Recording failed or timed out in silence.")
    else:
        file_size = os.path.getsize(audio_path)
        duration = time.time() - start
        print(f"\n✅ Recording finished in {duration:.2f}s.")
        print(f"   Audio saved to: {audio_path} ({file_size} bytes)")
        if file_size < 10000:
            print("   ⚠️ WARNING: File is extremely small. VAD likely stripped out all audio as pure noise.")
        else:
            print("   Playing back the VAD-filtered recording:")
            audio_utils.play_audio_file(str(audio_path))
    input("\nPress Enter to return to menu...")

def test_stt_engines():
    print_header("3. Speech-To-Text (Offline & Online)")
    if not os.path.exists(LAST_AUDIO):
        print(f"❌ No audio file found at {LAST_AUDIO}. Please run Test 2 (Microphone) first.")
        input("\nPress Enter to return to menu...")
        return
        
    print("\nExecuting OFFLINE Vosk Transcription...")
    start = time.time()
    if audio_utils.load_vosk_model():
        offline_text = audio_utils.quick_stt(LAST_AUDIO)
        print(f"\n   RESULT: '{offline_text}' (took {time.time() - start:.2f}s)")
    else:
        print("\n   ❌ Failed to load Vosk model.")
        
    print("\nExecuting ONLINE Transcription (Google/Gemini)...")
    start = time.time()
    online_text = audio_utils.online_stt(LAST_AUDIO)
    print(f"\n   RESULT: '{online_text}' (took {time.time() - start:.2f}s)")
    
    input("\nPress Enter to return to menu...")

def test_command_routing():
    print_header("4. Command Routing (Text Simulation)")
    print("Type a phrase exactly as if the STT engine had parsed it.")
    text = input("\nInput Phrase: ").strip()
    
    if not text:
        return

    print("\n[A] Checking Offline Commands First...")
    cmd = match_offline_command(text)
    if cmd:
        print(f"    ✅ Matched Offline Command: '{cmd}'")
        resp = process_offline_command(cmd)
        print(f"    🤖 RK AI Response Action:\n    {resp}")
        print("\nNote: Since an offline command matched, this would NOT be sent to Gemini.")
    else:
        print("    ❌ No offline command matched.")
        print("\n[B] Sending to Gemini (Online Mode Simulation)...")
        print("    Querying Gemini API directly...")
        try:
            prompt = f"User said: {text}\nRespond as a helpful AI assistant in raw JSON format."
            gemini_resp = generate_response(prompt)
            print("    🤖 Gemini Raw JSON Response:\n")
            print(f"    {gemini_resp}")
        except Exception as e:
            print(f"    ❌ Gemini Error: {e}")
            
    input("\nPress Enter to return to menu...")

def test_offline_smollm():
    print_header("5. Experimental Offline SmolLM (135m)")
    print("This will test a fully-local, quantized LLM completely on-device.")
    print("WARNING: On a Pi Zero W, token generation can be slower than 0.5 token/sec.")
    text = input("\nPrompt for SmolLM: ").strip()
    if text:
        result = _get_smollm_response(text)
        print(f"\n🤖 SmolLM Output:\n   {result}")
    
    input("\nPress Enter to return to menu...")

def test_third_party():
    print_header("6. Third Party Integrations")
    print("Fetching Weather...")
    w = fetch_weather()
    if w:
        print(f"✅ Weather success: {w.get('current', {}).get('temp_c')}C in {w.get('location', {}).get('name')}")
    else:
        print("❌ Weather failed.")
        
    print("\nFetching News...")
    n = fetch_news()
    if len(n) > 50:
         print(f"✅ News success. ({len(n)} characters parsed)")
    else:
         print(f"❌ News failed or too short. ('{n}')")
         
    input("\nPress Enter to return to menu...")

def main_menu():
    while True:
        os.system('clear' if os.name == 'posix' else 'cls')
        print("=" * 60)
        print(" RK AI - THE DEVELOPER SUITE ")
        print("=" * 60)
        print(" 1. Test Network & Configuration")
        print(" 2. Test Microphone & WebRTC VAD")
        print(" 3. Test Speech-To-Text (Vosk & Online)")
        print(" 4. Test Text Command Routing & Gemini")
        print(" 5. Test Experimental Offline SmolLM")
        print(" 6. Test Third-Party Integrations")
        print(" 0. Exit")
        print("-" * 60)
        
        choice = input("Select a module: ").strip()
        
        if choice == '1': test_network_and_config()
        elif choice == '2': test_microphone_and_vad()
        elif choice == '3': test_stt_engines()
        elif choice == '4': test_command_routing()
        elif choice == '5': test_offline_smollm()
        elif choice == '6': test_third_party()
        elif choice == '0':
            print("\nExiting Developer Suite. Run `sudo systemctl restart rk-assistant` to resume normal operation.")
            break

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\nExiting Developer Suite.")
