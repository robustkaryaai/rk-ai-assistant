
import os
import sys
import time
from pathlib import Path

# Add project root to path
SCRIPT_DIR = Path(__file__).parent
sys.path.append(str(SCRIPT_DIR))

from rk_assistant.config import GEMINI_API_KEY, GEMINI_MODEL_PRIMARY, GEMINI_API_KEY_BACKUP
from rk_assistant.audio_utils import record_until_silence

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Please install google-genai: pip install google-genai")
    sys.exit(1)

def main():
    print("🎙️  Recording audio (Speak now!)...")
    audio_path = record_until_silence(silence_duration=1.5)
    
    if not audio_path or not os.path.exists(audio_path):
        print("❌ No audio recorded.")
        return

    print(f"✅ Audio saved to: {audio_path}")
    
    # Read audio
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    print(f"🚀 Sending to Gemini ({GEMINI_MODEL_PRIMARY})...")
    
    client = genai.Client(api_key=GEMINI_API_KEY or GEMINI_API_KEY_BACKUP)
    
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL_PRIMARY,
            contents=[
                types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
                "Transcribe this audio exactly as spoken."
            ]
        )
        
        print("\n📝 Transcription:")
        print("-" * 20)
        print(response.text)
        print("-" * 20)
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
