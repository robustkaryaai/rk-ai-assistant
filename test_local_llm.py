#!/usr/bin/env python3
"""
Test script to load SmolLM-135M-Instruct on Raspberry Pi Zero W.
This is highly experimental and likely to hit memory limits or unsupported instructions.
"""
import os
import sys
import time
from pathlib import Path

# Adjust memory limits assuming 512MB total RAM (Pi Zero W)
# We need to leave at least 150MB for the OS and Python runtime
os.environ["LLAMA_CPP_MAX_MEM"] = "300000000"  # 300MB cap

# Path to the downloaded model
MODEL_DIR = Path("/home/raspberrypi/Documents/rk-ai-assistant-main/rk_assistant/model")
MODEL_FILE = MODEL_DIR / "SmolLM-135M-Instruct-Q4_K_M.gguf"

if not MODEL_FILE.exists():
    print(f"[Error] Model not found at {MODEL_FILE}")
    print("Run: curl -L \"https://huggingface.co/lmstudio-community/SmolLM-135M-Instruct-GGUF/resolve/main/SmolLM-135M-Instruct-Q4_K_M.gguf\" -o \"rk_assistant/model/SmolLM-135M-Instruct-Q4_K_M.gguf\"")
    sys.exit(1)

try:
    print(f"Loading '{MODEL_FILE.name}'...")
    print("Warning: This may take several minutes or crash the OS (OOM) on Pi Zero W.")
    start_time = time.time()
    
    from llama_cpp import Llama
    
    # Minimal memory settings
    llm = Llama(
        model_path=str(MODEL_FILE),
        n_ctx=256,         # Tiny context to save RAM
        n_threads=1,       # Pi Zero is single core
        n_batch=8,         # Tiny batch processing
        use_mlock=False,   # Don't lock memory (let OS swap if desperate)
        use_mmap=True,     # Memory map the weights
        verbose=False
    )
    
    load_time = time.time() - start_time
    print(f"✅ Model loaded successfully in {load_time:.1f} seconds!")
    
    print("\n--- Testing Inference ---")
    prompt = "<|im_start|>user\nHello! Who are you?<|im_end|>\n<|im_start|>assistant\n"
    
    print(f"Prompt: {prompt.strip()}")
    print("Generating response... (This could be very slow)")
    
    inf_start = time.time()
    output = llm(
        prompt,
        max_tokens=32,
        stop=["<|im_end|>"],
        echo=False
    )
    inf_time = time.time() - inf_start
    
    text = output['choices'][0]['text']
    print(f"\n✅ Output: {text.strip()}")
    print(f"⏱️ Inference time: {inf_time:.1f} seconds")
    
except Exception as e:
    print(f"\n❌ FATAL: Model failed to load or run. Pi Zero W is not capable.")
    print(f"Error Details: {e}")
