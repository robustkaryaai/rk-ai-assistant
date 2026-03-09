"""
Offline Playground:
Test Vosk STT, WebRTC Noise Suppression, and local scripts
without the overhead of main.py or internet connectivity.
"""
import os
import sys

# Ensure package context so relative imports work
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)
__package__ = "rk_assistant"

import time
from rk_assistant import audio_utils
from rk_assistant.offline_commands import match_offline_command, process_offline_command
from rk_assistant.config import LAST_AUDIO

def get_smollm_response(prompt: str) -> str:
    """
    Hook for testing SmolLM:135m.
    This requires `pip install llama-cpp-python` and downloading a GGUF model:
    e.g. `wget https://huggingface.co/lmstudio-community/SmolLM-135M-Instruct-GGUF/resolve/main/SmolLM-135M-Instruct-Q4_K_M.gguf`
    """
    try:
        from llama_cpp import Llama
    except ImportError:
        return "[SmolLM ERROR]: llama-cpp-python not installed. Run: pip install llama-cpp-python"
        
    model_path = os.path.join(current_dir, "model", "SmolLM-135M-Instruct-Q4_K_M.gguf")
    if not os.path.exists(model_path):
        return f"[SmolLM ERROR]: Model not found at {model_path}."
        
    try:
        print(f"\n[SmolLM] Loading 135m model (This takes RAM!)...")
        llm = Llama(model_path=model_path, n_ctx=256, verbose=False)
        print(f"\n[SmolLM] Generating response (Watch the token speed)...")
        
        output = llm(
            f"Question: {prompt}\nAnswer:",
            max_tokens=32, 
            stop=["Question:", "\n"],
            echo=False
        )
        return output['choices'][0]['text'].strip()
    except Exception as e:
        return f"[SmolLM ERROR]: {e}"

def test_offline_loop():
    print("=" * 60)
    print("RK AI - OFFLINE PLAYGROUND")
    print("Press Ctrl+C to exit.")
    print("=" * 60)
    
    # 1. Load Vosk
    if not audio_utils.load_vosk_model():
        print("Failed to load Vosk model. Please ensure start_rk.sh downloaded it.")
        return

    # 2. Main Loop
    while True:
        print("\n" + "-"*40)
        mode = input("Select Mode:\n[1] Test Base Offline Commands\n[2] Test SmolLM:135m Integration\nChoice (1/2): ").strip()
        
        input("\n[Press Enter to start recording...]")
        
        print("Listening (VAD + WebRTC Active)... Speak now.")
        
        # This will save clean audio to config.LAST_AUDIO
        audio_path = audio_utils.record_until_silence(
            out_path=LAST_AUDIO, 
            silence_duration=1.5
        )
        
        if not audio_path or not os.path.exists(audio_path):
            print("No audio detected.")
            continue
            
        print("Processing offline speech-to-text (Vosk)...")
        text = audio_utils.quick_stt(str(audio_path))
        
        if not text:
            print("Vosk heard nothing or audio was stripped by WebRTC VAD as pure noise.")
            continue
            
        print(f"\n[You]: {text}")
        
        if mode == '2':
            # EXPERIMENTAL SMOLLM
            resp = get_smollm_response(text)
            print(f"[SmolLM]: {resp}")
            audio_utils.speak(resp)
        else:
            # NORMAL OFFLINE COMMAND ROUTING
            cmd = match_offline_command(text)
            if cmd:
                print(f"Matched hardcoded offline command: '{cmd}'")
                resp = process_offline_command(cmd)
                print(f"[RK AI]: {resp}")
                
                # If the response is a special offline sound map
                if resp.startswith("_PLAY_OFFLINE_"):
                    print("(System would play a pre-recorded positive AI response here)")
                elif resp.startswith("_"):
                    print(f"(System Action Triggered: {resp})")
                else:
                    audio_utils.speak(resp)
            else:
                print("[RK AI]: Command not recognized offline. (Not in the 100+ command list)")

if __name__ == "__main__":
    try:
        test_offline_loop()
    except KeyboardInterrupt:
        print("\nExiting playground.")
