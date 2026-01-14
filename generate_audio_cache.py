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
    "Sure.",
    "Certainly.",
    "Of course.",
    "Right away.",
    "Done.",
    "Complete.",
    "Finished.",
    "Working.",
    "Processing.",
    "Please wait.",
    "One second.",
    "Just a moment.",
    "Hold on.",
    "Let me check.",
    "Checking now.",
    "Understood.",
    "Confirmed.",
    "Cancelled.",
    "Aborted.",
    "Resumed.",
    "Restarted.",
    "Enabled.",
    "Disabled.",
    "Connected.",
    "Disconnected.",
    "Ready.",
    "Loading.",
    "Starting.",
    "Stopping.",
    "Activating.",
    "Deactivating.",
    "Updating.",
    "Updated.",
    "Refreshed.",
    "Synced.",
    "Saved.",
    "Deleted.",
    "Removed.",
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

print(f"\n✅ Generated {total} offline responses")

# ============================================
# Online Command Acknowledgments (120 total)
# ============================================

print("\n" + "="*50)
print("Generating Online Acknowledgments (120 total)")
print("="*50 + "\n")

ONLINE_ACKNOWLEDGMENTS = [
    # General acknowledgments (20)
    "Got it, let me get that answer for you.",
    "Let me check that for you.",
    "Working on it.",
    "One moment please.",
    "I'll take care of that.",
    "Let me handle that for you.",
    "Processing your request.",
    "I'm on it.",
    "Give me a second.",
    "Let me look into that.",
    "Checking that now.",
    "I'll get right on that.",
    "Let me see what I can do.",
    "Working on your request.",
    "I'll help you with that.",
    "Let me fetch that for you.",
    "Looking that up now.",
    "I'll find that for you.",
    "Searching for that now.",
    "Let me pull that up.",
    
    # Image generation (15)
    "Creating your image.",
    "Generating your image now.",
    "Making that image for you.",
    "I'll create that image.",
    "Working on your image.",
    "Generating the image.",
    "Creating that picture for you.",
    "I'll make that image.",
    "Drawing that for you now.",
    "Creating the visual.",
    "Generating your artwork.",
    "Making your picture.",
    "Creating your graphic.",
    "Designing your image.",
    "Rendering your image now.",
    
    # Document creation (20)
    "Creating your presentation.",
    "Generating your presentation.",
    "Making your PowerPoint.",
    "Creating your slides.",
    "Working on your presentation.",
    "Creating your document.",
    "Generating your document.",
    "Making your document.",
    "Writing that document.",
    "Creating your file.",
    "Generating your Word document.",
    "Creating your text file.",
    "Making your doc.",
    "Writing that for you.",
    "Creating your report.",
    "Generating your report.",
    "Making your report.",
    "Compiling your document.",
    "Preparing your document.",
    "Drafting your document.",
    
    # Video creation (10)
    "Making your video.",
    "Creating your video.",
    "Generating your video.",
    "Working on your video.",
    "I'll create that video.",
    "Making that video for you.",
    "Generating the video now.",
    "Creating your clip.",
    "Producing your video.",
    "Rendering your video.",
    
    # Notes and planning (25)
    "Saving your note.",
    "Creating your note.",
    "I'll save that note.",
    "Taking that note.",
    "Recording your note.",
    "Creating your timetable.",
    "Making your timetable.",
    "Generating your schedule.",
    "Creating your schedule.",
    "Planning your timetable.",
    "Setting up your schedule.",
    "Planning that for you.",
    "I'll plan that.",
    "Creating your plan.",
    "Making your plan.",
    "Setting up your task.",
    "Creating your task.",
    "Adding that task.",
    "Scheduling that task.",
    "I'll add that to your tasks.",
    "Creating your reminder.",
    "Setting that reminder.",
    "I'll remind you about that.",
    "Adding that reminder.",
    "Scheduling your reminder.",
    
    # Educational tools (20)
    "Creating your lesson plan.",
    "Generating your lesson plan.",
    "Making your lesson plan.",
    "Planning your lesson.",
    "Creating your teaching plan.",
    "Generating your exam paper.",
    "Creating your exam.",
    "Making your test.",
    "Generating your quiz.",
    "Creating your assessment.",
    "Creating your grading sheet.",
    "Making your grading sheet.",
    "Generating your rubric.",
    "Creating your rubric.",
    "Making your grade sheet.",
    "Creating your class planner.",
    "Making your class planner.",
    "Generating your class schedule.",
    "Creating your teacher notes.",
    "Making your teaching notes.",
    
    # General creation (10)
    "Creating that for you.",
    "Generating that now.",
    "Making that.",
    "I'll create that.",
    "Working on creating that.",
    "Generating it now.",
    "Building that for you.",
    "I'll make that.",
    "Creating it now.",
    "Generating your file.",
]

online_total = 0
for ack in ONLINE_ACKNOWLEDGMENTS:
    generate_audio(ack, f"Online: {ack[:40]}")
    online_total += 1

print(f"\n✅ Generated {online_total} online acknowledgments")

# ============================================
# Summary
# ============================================

print("\n" + "="*50)
print("Audio Generation Complete!")
print("="*50)
print(f"\n✅ Offline responses: {total}")
print(f"✅ Online acknowledgments: {online_total}")
print(f"✅ Total generated: {total + online_total} audio files")
print(f"📁 Location: {AUDIO_DIR}")
print(f"💾 Total size: ~{sum(f.stat().st_size for f in AUDIO_DIR.glob('*.mp3')) / 1024 / 1024:.1f} MB")
print("\nNext steps:")
print("1. git add rk_assistant/audio_cache/")
print("2. git commit -m 'Add pre-generated TTS audio cache'")
print("3. git push origin main")
print("\nAll responses will now be instant! (~200ms)")
