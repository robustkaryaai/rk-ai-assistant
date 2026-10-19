#!/usr/bin/env python3
"""
RK AI Assistant — Interactive Microphone Diagnostic & Live STT Tester
Tests:
1. ALSA hardware capture levels & mixer controls
2. SpeechRecognition mic detection & ambient noise level
3. 5-second voice recording
4. Audio peak RMS & normalization check
5. Google STT test transcription
6. Speaker playback test
"""
import os
import sys
import time
import subprocess
from pathlib import Path

print("=" * 60)
print("🎙️  RK AI Assistant — Microphone Diagnostic & Live Test Tool")
print("=" * 60)

# 1. ALSA hardware capture check
print("\n[Step 1/5] Checking and setting ALSA hardware gain to 100%...")
controls = ["Capture", "Mic", "Internal Mic", "Digital"]
for c in controls:
    res = subprocess.run(["amixer", "sset", c, "100%"], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"  ✅ Control '{c}' set to 100%")

# 2. Check available recording devices
print("\n[Step 2/5] ALSA recording hardware (arecord -l):")
try:
    arecord_out = subprocess.check_output(["arecord", "-l"], text=True)
    for line in arecord_out.strip().splitlines():
        if "card" in line.lower():
            print(f"  🔊 {line}")
except Exception as e:
    print(f"  ⚠️ arecord -l failed: {e}")

# 3. SpeechRecognition detection
print("\n[Step 3/5] Testing SpeechRecognition library & Microphones...")
try:
    import speech_recognition as sr
    print(f"  ✅ speech_recognition installed (version {sr.__version__})")
    
    # Force PulseAudio / ALSA capture gain
    for c in ["Capture", "Mic", "Internal Mic", "Digital", "Input", "Boost"]:
        subprocess.run(["amixer", "sset", c, "100%"], capture_output=True)
    subprocess.run(["pactl", "set-source-volume", "@DEFAULT_SOURCE@", "100%"], capture_output=True)
    subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"], capture_output=True)
    subprocess.run(["amixer", "sset", "Master", "100%"], capture_output=True)

    mics = sr.Microphone.list_microphone_names()
    print(f"  🎙️ Detected {len(mics)} microphone device(s):")
    for i, name in enumerate(mics):
        print(f"     [{i}] {name}")
except Exception as e:
    print(f"  ❌ speech_recognition error: {e}")
    sys.exit(1)

# 4. Interactive Live Recording
test_wav = Path("/tmp/rk_mic_test.wav")
if test_wav.exists():
    test_wav.unlink()

print("\n[Step 4/5] 🎤 RECORDING TEST:")
print("👉 Prepare to speak clearly into the microphone for 5 seconds...")
for s in range(3, 0, -1):
    print(f"   Starting in {s}...", end="\r", flush=True)
    time.sleep(1)
print("   🔴 RECORDING NOW! Say: 'Hello RK, what is the weather today?'", flush=True)

try:
    r = sr.Recognizer()
    r.energy_threshold = 50
    r.dynamic_energy_threshold = True
    r.dynamic_energy_ratio = 1.3
    r.phrase_threshold = 0.1

    # 16000 Hz is Google's optimal acoustic model sample rate
    with sr.Microphone(sample_rate=16000) as source:
        r.adjust_for_ambient_noise(source, duration=0.8)
        r.energy_threshold = max(r.energy_threshold, 50)
        print(f"   Calibrated Energy Threshold: {r.energy_threshold:.0f}")
        print("   Listening for 5 seconds...")
        audio = r.listen(source, timeout=8, phrase_time_limit=6)
    
    # Save audio
    with open(test_wav, "wb") as f:
        f.write(audio.get_wav_data())

    file_size = test_wav.stat().st_size
    print(f"  ✅ Audio captured successfully! File size: {file_size:,} bytes")

    # Measure RMS energy & peak
    try:
        import audioop
        raw = audio.get_raw_data()
        rms = audioop.rms(raw, 2)
        peak = audioop.max(raw, 2)
        print(f"  📊 Raw Audio metrics: Peak={peak}/32767 | RMS Energy={rms}")
    except Exception:
        pass

except Exception as e:
    print(f"  ❌ Failed to record from microphone: {e}")
    sys.exit(1)

# 5. Live Google STT Transcription Test
print("\n[Step 5/5] Testing Google STT transcription on captured audio...")
for lang in ["en-US", "en-IN"]:
    print(f"\n--- Testing language: {lang} ---")
    # A. Test raw captured audio
    try:
        with sr.AudioFile(str(test_wav)) as source:
            raw_audio = r.record(source)
        res_raw = r.recognize_google(raw_audio, language=lang).strip()
        print(f"  ✅ [Raw Audio ({lang})] -> \"{res_raw}\"")
    except sr.UnknownValueError:
        print(f"  ⚠️ [Raw Audio ({lang})] Unrecognized.")
    except Exception as e:
        print(f"  ❌ [Raw Audio ({lang})] Error: {e}")

    # B. Test boosted audio
    try:
        import audioop
        with sr.AudioFile(str(test_wav)) as source:
            boosted_audio = r.record(source)
        raw_bytes = boosted_audio.get_raw_data()
        peak = audioop.max(raw_bytes, 2)
        if peak > 0:
            boost = min(31000 / peak, 35.0)
            boosted_bytes = audioop.mul(raw_bytes, 2, boost)
            boosted_audio = sr.AudioData(boosted_bytes, boosted_audio.sample_rate, boosted_audio.sample_width)
            res_boosted = r.recognize_google(boosted_audio, language=lang).strip()
            print(f"  ✅ [Boosted Audio ({lang})] -> \"{res_boosted}\"")
        else:
            print(f"  ⚠️ [Boosted Audio] Peak was 0.")
    except sr.UnknownValueError:
        print(f"  ⚠️ [Boosted Audio ({lang})] Unrecognized.")
    except Exception as e:
        print(f"  ❌ [Boosted Audio ({lang})] Error: {e}")

print("\n🔊 Would you like to play back what was recorded through your speaker? (y/n)")
try:
    ans = input().strip().lower()
    if ans == "y":
        print("Playing /tmp/rk_mic_test.wav...")
        subprocess.run(["aplay", str(test_wav)])
except Exception:
    pass

print("\nDone!")
