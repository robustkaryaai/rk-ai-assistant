"""
Simple audio utilities - just what we need.
"""
import subprocess


def speak(text):
    """
    Convert text to speech using espeak (pre-installed on Pi).
    """
    try:
        print(f"🔊 {text}", flush=True)
        subprocess.run(['espeak', text], check=False, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"⚠ Speak error: {e}", flush=True)
