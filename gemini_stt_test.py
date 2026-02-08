
import asyncio
import os
import sys

# Add project root to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(SCRIPT_DIR)

from rk_assistant.config import GEMINI_API_KEY, GEMINI_MODEL_PRIMARY, GEMINI_API_KEY_BACKUP

try:
    import sounddevice as sd
    import numpy as np
    import google.generativeai as genai
    from google.generativeai.types import LiveConnectConfig
except ImportError as e:
    print(f"❌ Missing dependencies: {e}")
    print("Please install: pip install sounddevice numpy google-generativeai")
    print("Also ensure PortAudio is installed: sudo apt-get install libportaudio2")
    sys.exit(1)

# -----------------------------
# CONFIGURATION
# -----------------------------
API_KEY = GEMINI_API_KEY or GEMINI_API_KEY_BACKUP
MODEL_NAME = GEMINI_MODEL_PRIMARY
SAMPLE_RATE = 16000       # Gemini Native Audio expects 16kHz mono PCM
CHUNK_DURATION = 0.5      # seconds per audio chunk

# -----------------------------
# AUDIO CAPTURE GENERATOR
# -----------------------------
def audio_stream_generator():
    """Yields microphone audio chunks as bytes for Gemini Live API."""
    print(f"🎤 Device: {sd.default.device}")
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16') as stream:
        print("🎤 Stream started...")
        while True:
            audio_chunk, overflowed = stream.read(int(SAMPLE_RATE * CHUNK_DURATION))
            if overflowed:
                print("⚠️ Audio overflow!")
            yield audio_chunk.tobytes()

# -----------------------------
# MAIN ASYNC FUNCTION
# -----------------------------
async def main():
    if not API_KEY:
        print("❌ No API Key found in config.")
        return

    # Configure Gemini SDK
    genai.configure(api_key=API_KEY)

    print(f"🚀 Connecting to Gemini Live ({MODEL_NAME})...")
    print("Press Ctrl+C to stop.")

    try:
        # Create a Live API connection with Native Audio enabled
        async with genai.live.connect(
            model=MODEL_NAME,
            config=LiveConnectConfig(
                modalities=["audio", "text"],  # Enable audio input + text output
                # audio_format="pcm16",        # SDK might infer or require specific enum
                # sample_rate=SAMPLE_RATE
                response_modalities=["text"]   # Request text response (transcription/dialog)
            )
        ) as session:
            print("✅ Connected!")
            print("🎤 Listening...")

            # Start sending audio in background
            async def send_audio():
                for chunk in audio_stream_generator():
                    await session.send_input(chunk) # send_audio or send_input depending on SDK version

            # Start receiving transcriptions
            async def receive_transcripts():
                async for event in session.receive():
                    text = None
                    # Handle different event types from SDK
                    if hasattr(event, "text") and event.text:
                        text = event.text
                    elif hasattr(event, "server_content") and event.server_content:
                         # Inspect server_content logic if needed
                         pass
                    
                    if text:
                        print(f"📝 Transcript: {text}", flush=True)

            await asyncio.gather(send_audio(), receive_transcripts())

    except Exception as e:
        print(f"❌ Error: {e}")

# -----------------------------
# ENTRY POINT
# -----------------------------
if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
             asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
