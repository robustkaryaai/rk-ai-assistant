#!/usr/bin/env python3
"""
Pre-generate all TTS audio files for instant playback.
Run this script once to generate all audio, then commit to git.
"""

import os
import hashlib
from pathlib import Path
from gtts import gTTS

# Pre-generated audio directory (committed to git)
AUDIO_DIR = Path(__file__).parent / "rk_assistant" / "audio_cache"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

def get_audio_filename(text):
    """Get consistent filename for text."""
    text_hash = hashlib.md5(text.encode()).hexdigest()
    return f"{text_hash}.mp3"

def generate_audio(text, description=""):
    """Generate gTTS audio for text."""
    filename = get_audio_filename(text)
    filepath = AUDIO_DIR / filename
    
    if filepath.exists():
        print(f"✓ Cached: {description or text[:30]}")
        return filepath
    
    print(f"🔊 Generating: {description or text[:30]}...")
    try:
        tts = gTTS(text=text, lang='en')
        tts.save(str(filepath))
        print(f"   Saved: {filename}")
        return filepath
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return None

# ============================================
# Offline Command Responses (102 total)
# ============================================

print("\n" + "="*50)
print("Generating Offline Command Responses")
print("="*50 + "\n")

OFFLINE_RESPONSES = {
    # Greetings (21 responses)
    "hello": ["Hello! How can I help you?", "Hi there!", "Hello! Nice to hear from you!"],
    "hi": ["Hi! What can I do for you?", "Hey there!", "Hi! I'm listening."],
    "hey": ["Hey! How can I assist?", "Hey there!", "Hey! What's up?"],
    "good morning": ["Good morning! Hope you have a great day!", "Good morning! How can I help?"],
    "good afternoon": ["Good afternoon! What can I do for you?", "Good afternoon!"],
    "good evening": ["Good evening! How may I assist?", "Good evening!"],
    "good night": ["Good night! Sleep well!", "Good night! See you tomorrow!"],
    
    # Conversational (27 responses)
    "how are you": ["I'm doing great! Thanks for asking.", "I'm fine, thank you! How about you?"],
    "what's up": ["Not much, just waiting to help you!", "All good here! What about you?"],
    "thank you": ["You're welcome!", "Happy to help!", "Anytime!"],
    "thanks": ["No problem!", "You're welcome!", "My pleasure!"],
    "okay": ["Okay!", "Got it!", "Understood!"],
    "yes": ["Yes!", "Affirmative!", "Okay!"],
    "no": ["No problem!", "Alright!", "Okay!"],
    "goodbye": ["Goodbye! Take care!", "See you later!", "Bye! Have a great day!"],
    "bye": ["Bye!", "See you!", "Goodbye!"],
    
    # Music controls (15 responses)
    "play music": ["No cached music URL. Please ask online."],
    "pause music": ["Paused."],
    "stop music": ["Paused."],
    "volume up": ["Volume up."],
    "volume down": ["Volume down."],
    "mute": ["Muted."],
    "unmute": ["Unmuted."],
    
    # Time/Date (6 responses)
    "time": ["It is %TIME%."],  # Will be formatted at runtime
    "date": ["Today is %DATE%."],  # Will be formatted at runtime
    
    # Announcements (3 responses)
    "announcement": ["Ready for your announcement."],
    
    # Alarms (6 responses)
    "set alarm": ["Alarm set for %TIME%."],
    "cancel alarm": ["Canceled %COUNT% alarm."],
    
    # System (6 responses)
    "battery": ["Battery information not available in offline mode."],
    "status": ["System is running in offline mode."],
    
    # Assistant info (9 responses)
    "who are you": ["I am RK AI, your personal assistant created by RK Innovators."],
    "help": ["I can help with music playback, alarms, time, date, and basic commands. For more features, connect to the internet."],
    "commands": ["I support greetings, music controls, time and date queries, alarms, and system commands. Ask me anything!"],
    
    # Nice responses (12 responses)
    "nice": ["Thank you!", "Glad you liked it!", "Great to hear!", "Awesome!"],
}

# Additional common responses
COMMON_RESPONSES = [
    "Sorry, that might require internet.",
    "Sorry, I don't know that.",
    "I'm listening.",
    "Paused.",
    "Playing.",
    "Stopped.",
]

# Generate all offline responses
total = 0
for category, responses in OFFLINE_RESPONSES.items():
    for response in responses:
        if "%TIME%" not in response and "%DATE%" not in response and "%COUNT%" not in response:
            generate_audio(response, f"Offline: {category}")
            total += 1

# Generate common responses
for response in COMMON_RESPONSES:
    generate_audio(response, f"Common: {response}")
    total += 1

# ============================================
# Online Command Acknowledgments
# ============================================

print("\n" + "="*50)
print("Generating Online Acknowledgments")
print("="*50 + "\n")

ONLINE_ACKNOWLEDGMENTS = [
    # General
    "Got it, let me get that answer for you.",
    "Let me check that for you.",
    "Working on it.",
    "One moment please.",
    
    # Specific actions
    "Creating your image.",
    "Generating your presentation.",
    "Creating your document.",
    "Making your video.",
    "Saving your note.",
    "Creating your timetable.",
    "Planning that for you.",
    "Setting up your task.",
    "Creating your lesson plan.",
    "Generating your exam paper.",
    "Creating your grading sheet.",
]

for ack in ONLINE_ACKNOWLEDGMENTS:
    generate_audio(ack, f"Online: {ack}")
    total += 1

# ============================================
# Summary
# ============================================

print("\n" + "="*50)
print("Audio Generation Complete!")
print("="*50)
print(f"\n✅ Generated {total} audio files")
print(f"📁 Location: {AUDIO_DIR}")
print(f"💾 Total size: ~{sum(f.stat().st_size for f in AUDIO_DIR.glob('*.mp3')) / 1024 / 1024:.1f} MB")
print("\nNext steps:")
print("1. git add rk_assistant/audio_cache/")
print("2. git commit -m 'Add pre-generated TTS audio cache'")
print("3. git push origin main")
print("\nAll responses will now be instant! (~200ms)")
