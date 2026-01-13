"""
Simple audio utilities - just what we need.
"""
import subprocess
import socket


def is_online():
    """Quick check if internet is available."""
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=2)
        return True
    except:
        return False


def speak(text, use_gtts=False):
    """
    Convert text to speech.
    Uses espeak by default for instant responses (10-50ms).
    Set use_gtts=True for better quality but slower (3-4s).
    """
    try:
        print(f"🔊 {text}", flush=True)
        
        # Use gTTS only if explicitly requested AND online
        if use_gtts and is_online():
            try:
                from gtts import gTTS
                import tempfile
                from pathlib import Path
                
                tts = gTTS(text=text, lang='en')
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as fp:
                    temp_path = fp.name
                    tts.save(temp_path)
                
                # Play using mpg123 (more reliable than ffplay on Pi)
                subprocess.run(['mpg123', '-q', temp_path], check=False, stderr=subprocess.DEVNULL)
                
                try:
                    Path(temp_path).unlink()
                except:
                    pass
                return
            except Exception as e:
                print(f"⚠ gTTS failed, falling back to espeak: {e}", flush=True)
        
        # Default: espeak (instant, ~10-50ms response)
        subprocess.run(['espeak', text], check=False, stderr=subprocess.DEVNULL)
        
    except Exception as e:
        print(f"⚠ Speak error: {e}", flush=True)
