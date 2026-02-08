
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
    from google import genai
    from google.genai.types import LiveConnectConfig
except ImportError as e:
    print(f"❌ Missing dependencies: {e}")
    print("Please install: pip install sounddevice numpy google-genai")
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

    # Create Client (google-genai SDK style)
    client = genai.Client(api_key=API_KEY, http_options={'api_version': 'v1alpha'}) # Experimental features often need alpha? Or just standard.

    print(f"🚀 Connecting to Gemini Live ({MODEL_NAME})...")
    print("Press Ctrl+C to stop.")

    try:
        # Create a Live API connection with Native Audio enabled
        # The new SDK uses client.aio.live.connect
        async with client.aio.live.connect(
            model=MODEL_NAME,
            config=LiveConnectConfig(
                response_modalities=["TEXT"],  # Request text transcription
                speech_config={"voice_config": {"prebuilt_voice_config": {"voice_name": "Puck"}}} # Optional config example
            )
        ) as session:
            print("✅ Connected!")
            print("🎤 Listening...")

            # Start sending audio in background
            async def send_audio():
                for chunk in audio_stream_generator():
                    await session.send_input({"mime_type": "audio/pcm;rate=16000", "data": chunk})

            # Start receiving transcriptions
            async def receive_transcripts():
                async for response in session.receive():
                    text = None
                    # Handle different response types from SDK
                    # Usually response.server_content.model_turn.parts[0].text
                    if response.server_content and response.server_content.model_turn:
                        for part in response.server_content.model_turn.parts:
                            if part.text:
                                print(f"📝 Transcript: {part.text}", flush=True)

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
