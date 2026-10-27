#!/usr/bin/env python3
"""
RK AI Assistant — Interactive Microphone Tuner & Live Calibration Studio
Allows you to:
1. View live input audio meter (VU meter in terminal) to see room silence vs voice
2. Adjust hardware & software gain (ALSA / PulseAudio volume) interactively
3. Tune energy threshold and test real-time Google Speech Recognition
4. Test playback of your recorded voice to hear clarity/noise directly through speakers
5. Save optimal mic settings directly into the assistant configuration
"""

import os
import sys
import time
import json
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MIC_CONFIG_FILE = BASE_DIR / "data" / "mic_config.json"

try:
    import speech_recognition as sr
except ImportError:
    print("❌ speech_recognition is not installed. Run: pip install SpeechRecognition")
    sys.exit(1)

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False


def clear_screen():
    print("\033[H\033[J", end="")


def get_pactl_volume():
    try:
        out = subprocess.check_output(["pactl", "get-source-volume", "@DEFAULT_SOURCE@"], text=True)
        # Output looks like: Volume: front-left: 65536 / 100% / 0.00 dB, ...
        import re
        match = re.search(r"(\d+)%", out)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return 100


def set_pactl_volume(vol_percent):
    vol_percent = max(10, min(300, vol_percent))
    try:
        subprocess.run(["pactl", "set-source-volume", "@DEFAULT_SOURCE@", f"{vol_percent}%"], check=True)
        for control in ["Capture", "Mic", "Internal Mic", "Digital", "Boost"]:
            subprocess.run(["amixer", "sset", control, "100%"], capture_output=True)
        return True
    except Exception as e:
        print(f"⚠️ Failed to set volume: {e}")
        return False


def load_mic_config():
    if MIC_CONFIG_FILE.exists():
        try:
            return json.loads(MIC_CONFIG_FILE.read_text())
        except Exception:
            pass
    return {
        "source_volume_percent": 150,
        "energy_threshold": 40,
        "dynamic_energy_ratio": 1.4,
        "phrase_threshold": 0.15
    }


def save_mic_config(cfg):
    MIC_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    MIC_CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    print(f"\n💾 Saved mic config to {MIC_CONFIG_FILE}!")


def live_vu_meter(duration_sec=10):
    """Shows a live ASCII VU volume meter so you can see background noise vs speaking."""
    print(f"\n📊 Live Audio VU Meter running for {duration_sec}s (Speak now to see levels)...")
    print("Press Ctrl+C to stop early.\n")

    r = sr.Recognizer()
    with sr.Microphone(sample_rate=16000) as source:
        start = time.time()
        try:
            while time.time() - start < duration_sec:
                # Capture 0.2s raw audio chunk
                raw_chunk = source.stream.read(source.CHUNK)
                if not raw_chunk:
                    continue

                if HAVE_NUMPY:
                    samples = np.frombuffer(raw_chunk, dtype=np.int16)
                    rms = int(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
                    peak = int(np.max(np.abs(samples)))
                else:
                    import audioop
                    rms = audioop.rms(raw_chunk, 2)
                    peak = audioop.max(raw_chunk, 2)

                # Map RMS (0 to 12000) into 40-character bar
                bars = min(40, int(rms / 150))
                meter = "█" * bars + "░" * (40 - bars)

                # Color-code: Green for soft, Yellow for good speech, Red for peak
                if peak > 28000:
                    status = "\033[91m🔥 CLIPPING / TOO LOUD\033[0m"
                elif rms > 400:
                    status = "\033[92m🗣️ VOICE DETECTED\033[0m"
                else:
                    status = "\033[90m💤 SILENCE / AMBIENT\033[0m"

                sys.stdout.write(f"\r[{meter}] RMS: {rms:5d} | Peak: {peak:5d}  {status}   ")
                sys.stdout.flush()
                time.sleep(0.04)
        except KeyboardInterrupt:
            pass
    print("\n")


def test_recording_and_stt(energy_threshold=40):
    r = sr.Recognizer()
    r.energy_threshold = energy_threshold
    r.dynamic_energy_threshold = True
    r.dynamic_energy_ratio = 1.4
    r.phrase_threshold = 0.15

    print(f"\n🎙️ Recording Test (Energy Threshold = {energy_threshold})...")
    print("👉 Speak a phrase now (e.g. 'Hello RK what time is it?')...")

    with sr.Microphone(sample_rate=16000) as source:
        r.adjust_for_ambient_noise(source, duration=0.8)
        print(f"   [Calibrated Threshold]: {r.energy_threshold:.1f}")
        try:
            audio = r.listen(source, timeout=6, phrase_time_limit=5)
        except sr.WaitTimeoutError:
            print("⚠️ No speech detected (Timed out). Try raising microphone gain or speaking louder.")
            return None

    test_wav = Path("/tmp/rk_mic_tuning.wav")
    with open(test_wav, "wb") as f:
        f.write(audio.get_wav_data())

    # Measure level
    try:
        import audioop
        raw = audio.get_raw_data()
        rms = audioop.rms(raw, 2)
        peak = audioop.max(raw, 2)
        print(f"   [Captured Audio]: RMS={rms} | Peak={peak}/32767")
    except Exception:
        pass

    # STT Test
    print("\n   [Google STT Transcription]:")
    try:
        transcription = r.recognize_google(audio, language="en-IN").strip()
        print(f"   ✅ Recognized: \"{transcription}\"")
    except sr.UnknownValueError:
        print("   ⚠️ Audio was captured, but speech was unclear or noise.")
    except Exception as e:
        print(f"   ❌ STT Error: {e}")

    # Playback prompt
    try:
        play_ans = input("\n🔊 Play back this recording through speaker at 100% volume? (y/N): ").strip().lower()
        if play_ans == "y":
            # Force speaker sink volume to 100% for playback
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"], capture_output=True)
            subprocess.run(["amixer", "sset", "Master", "100%"], capture_output=True)
            print("🔊 Playing back through speaker at 100% volume...")
            subprocess.run(["aplay", "-q", str(test_wav)])
    except Exception:
        pass

    return test_wav


def main():
    cfg = load_mic_config()

    while True:
        clear_screen()
        current_vol = get_pactl_volume()
        print("=" * 60)
        print("🎛️  RK AI Assistant — Interactive Microphone Tuning Studio")
        print("=" * 60)
        print(f" 1. Current Hardware / PulseAudio Source Gain : {current_vol}%")
        print(f" 2. Base Energy Detection Threshold           : {cfg.get('energy_threshold', 40)}")
        print(f" 3. Dynamic Ratio                             : {cfg.get('dynamic_energy_ratio', 1.4)}")
        print("=" * 60)
        print(" [v] Live VU Meter (See background noise vs speech live)")
        print(" [t] Test 5-Second Speech & Google STT Transcription")
        print(" [+] Increase Mic Gain (+25%)")
        print(" [-] Decrease Mic Gain (-25%)")
        print(" [e] Change Energy Threshold manually")
        print(" [s] Save & Apply Settings for RK AI Assistant")
        print(" [q] Quit")
        print("=" * 60)

        choice = input("\nSelect an option: ").strip().lower()

        if choice == "v":
            live_vu_meter(10)
            input("Press Enter to continue...")
        elif choice == "t":
            test_recording_and_stt(cfg.get("energy_threshold", 40))
            input("\nPress Enter to return to menu...")
        elif choice in ("+", "="):
            new_v = current_vol + 25
            set_pactl_volume(new_v)
            cfg["source_volume_percent"] = new_v
        elif choice in ("-", "_"):
            new_v = max(25, current_vol - 25)
            set_pactl_volume(new_v)
            cfg["source_volume_percent"] = new_v
        elif choice == "e":
            val = input(f"Enter new Energy Threshold (current: {cfg.get('energy_threshold', 40)}): ").strip()
            if val.isdigit():
                cfg["energy_threshold"] = int(val)
        elif choice == "s":
            cfg["source_volume_percent"] = current_vol
            save_mic_config(cfg)
            input("Press Enter to continue...")
        elif choice == "q":
            print("\nExiting. Good luck!")
            break


if __name__ == "__main__":
    main()
