"""
STT Client for RK Assistant.
Handles audio transcription using Groq (fast) or Google (fallback).
"""
import io
import os
import requests
import speech_recognition as sr
from typing import Optional
from .config import GROQ_API_KEY, STT_ENGINE

def transcribe_groq(audio_data: sr.AudioData) -> Optional[str]:
    """
    Transcribe audio using Groq Whisper API (ultra-fast).
    """
    if not GROQ_API_KEY:
        print("[stt] GROQ_API_KEY not found.")
        return None

    try:
        # Get WAV data
        wav_data = audio_data.get_wav_data()
        
        # Groq API endpoint
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}"
        }
        
        # Prepare multipart upload
        # Filename 'audio.wav' is important for Groq to detect mime type
        files = {
            "file": ("audio.wav", wav_data, "audio/wav"),
            "model": (None, "whisper-large-v3"),
            "response_format": (None, "json"),
            "language": (None, "en")
        }
        
        print("[stt] Sending audio to Groq...", flush=True)
        response = requests.post(url, headers=headers, files=files, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            text = result.get("text", "").strip()
            print(f"[stt] Groq transcript: '{text}'")
            return text
        else:
            print(f"[stt] Groq failed: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"[stt] Groq error: {e}")
        return None

def transcribe_audio(recognizer: sr.Recognizer, audio: sr.AudioData) -> str:
    """
    Transcribe audio using configured engine (Groq or Google).
    Raises UnknownValueError or RequestError on failure.
    """
    text = None
    
    # methods:
    use_groq = STT_ENGINE == "groq"
    
    if use_groq and GROQ_API_KEY:
        try:
            text = transcribe_groq(audio)
        except Exception as e:
            print(f"[stt] Groq exception: {e}")
    
    if text:
        return text
        
    # Fallback to Google
    if use_groq:
        print("[stt] Falling back to Google STT...")
    
    print("[stt] Sending audio to Google...", flush=True)
    return recognizer.recognize_google(audio)
