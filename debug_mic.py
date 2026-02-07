import speech_recognition as sr
import os

print("=== Microphone Debug Info ===")
print(f"Current MIC_DEVICE_INDEX env var: {os.getenv('MIC_DEVICE_INDEX')}")

print("\nAvailable Devices:")
try:
    mics = sr.Microphone.list_microphone_names()
    for i, name in enumerate(mics):
        print(f"Index {i}: {name}")
except Exception as e:
    print(f"Error listing mics: {e}")

print("\n=== Testing Capture (Sensitive Mode) ===")
r = sr.Recognizer()
r.energy_threshold = 50  # Super sensitive
r.dynamic_energy_threshold = False 

print(f"Threshold: {r.energy_threshold} (Dynamic: {r.dynamic_energy_threshold})")

try:
    with sr.Microphone() as source:
        print("Adjusting related to ambient noise (1s)...")
        r.adjust_for_ambient_noise(source, duration=1.0)
        print(f"New Threshold after adjustment: {r.energy_threshold}")
        
        print("Listening for 5s... (Say something!)")
        try:
            audio = r.listen(source, timeout=5, phrase_time_limit=5)
            print("✅ Heard audio! Captured successfully.")
            
            # Verify length
            wav_data = audio.get_wav_data()
            print(f"Audio captured: {len(wav_data)} bytes")
            
        except sr.WaitTimeoutError:
            print("❌ Timeout: No speech detected.")
            
except Exception as e:
    print(f"❌ Error during test: {e}")
