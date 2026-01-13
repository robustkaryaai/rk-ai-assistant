"""
Simple audio utilities - just what we need.
"""
from gtts import gTTS
import subprocess
import tempfile
from pathlib import Path


def speak(text):
    """
    Convert text to speech using gTTS and play it.
    """
    try:
        print(f"🔊 Speaking: {text}", flush=True)
        
        # Generate speech
        tts = gTTS(text=text, lang='en')
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
            temp_path = fp.name
            tts.save(temp_path)
        
        # Play using ffplay (silent, close on completion)
        subprocess.run([
            'ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet',
            temp_path
        ], check=False)
        
        # Cleanup
        try:
            Path(temp_path).unlink()
        except:
            pass
            
    except Exception as e:
        print(f"⚠ Speak error: {e}", flush=True)
