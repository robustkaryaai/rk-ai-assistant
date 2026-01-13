"""
Simple, reliable voice recognition loop.
Based on user's working pattern - just listen, transcribe, check for wake word.
"""
import speech_recognition as sr
from .audio_utils_simple import speak
from .config import WAKE_WORD


def listen(recognizer, mic):
    """
    Listen for audio and transcribe using Google STT.
    Returns transcribed text or empty string.
    """
    with mic as source:
        print("🎤 Listening...", flush=True)
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        audio = recognizer.listen(source)
    
    try:
        command = recognizer.recognize_google(audio)
        print(f"✓ You said: {command}", flush=True)
        return command.lower()
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as e:
        print(f"⚠ STT service error: {e}", flush=True)
        return ""
    except Exception as e:
        print(f"⚠ Listen error: {e}", flush=True)
        return ""


def voice_loop(decoder_available, music_proc_holder, slug):
    """
    Main voice loop - continuously listen and respond when wake word detected.
    """
    recognizer = sr.Recognizer()
    mic = sr.Microphone()
    
    # Import handlers
    from . import local_handlers
    from .networking import send_to_backend_async
    
    speak("Radhe Radhe! RK is ready.")
    
    while True:
        command = listen(recognizer, mic)
        
        if not command:
            continue
        
        # Check for wake word
        if WAKE_WORD in command:
            print(f"🔔 Wake word detected!", flush=True)
            
            # Strip wake word to get actual command
            idx = command.find(WAKE_WORD)
            actual_command = command[idx + len(WAKE_WORD):].strip()
            
            if not actual_command:
                speak("Yes?")
                continue
            
            print(f"📝 Processing: '{actual_command}'", flush=True)
            
            # Handle exit
            if "exit" in actual_command or "stop" in actual_command or "shutdown" in actual_command:
                speak("Goodbye!")
                break
            
            # Quick local commands
            if "time" in actual_command:
                from datetime import datetime
                now = datetime.now().strftime("%H:%M")
                speak(f"The current time is {now}")
                continue
            
            # Try local handlers first
            try:
                from .gemini_client import classify_intent, GEMINI_AVAILABLE
                from .config import USE_GEMINI_DIRECT, GEMINI_API_KEY
                
                if USE_GEMINI_DIRECT and GEMINI_AVAILABLE and GEMINI_API_KEY:
                    intents = classify_intent(actual_command, api_key=GEMINI_API_KEY)
                    if intents and len(intents) > 0:
                        intent_name = intents[0].get("intent", "chat")
                        parameters = intents[0].get("parameters", {})
                        
                        local_intents = ["music", "alarm", "announcement", "chat", "general"]
                        if intent_name in local_intents:
                            response = local_handlers.handle_intent(intent_name, parameters, original_text=actual_command)
                            if response.get("reply"):
                                speak(response["reply"])
                            continue
            except Exception as e:
                print(f"⚠ Intent classification failed: {e}", flush=True)
            
            # Fallback to backend
            speak("Working on it...")
            send_to_backend_async(actual_command, slug)
        
        # If no wake word, just ignore silently
