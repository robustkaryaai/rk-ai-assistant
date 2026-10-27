#!/usr/bin/env python3
"""
RK AI Assistant — Interactive Microphone Tuning Studio & Live Loop Calibrator
Features:
1. Continuous Loop Mode: Records 3 seconds -> Plays back immediately through speaker at 100% ->
   prompts for single keystroke (+, -, or keep) to adjust gain on the fly!
2. Live VU Meter: Visual level bar in terminal to check silence vs voice.
3. PulseAudio + ALSA Unmute Safety: Guarantees mic isn't muted or clipped.
4. Auto-saves optimal settings to data/mic_config.json.
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
    """Retrieve current capture volume in %."""
    try:
        out = subprocess.check_output(["pactl", "get-source-volume", "@DEFAULT_SOURCE@"], text=True)
        import re
        match = re.search(r"(\d+)%", out)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return 100


def set_pactl_volume(vol_percent):
    """Sets PulseAudio capture source volume safely and un-mutes all mic channels."""
    vol_percent = max(10, min(500, vol_percent))
    try:
        # Set software source volume
        subprocess.run(["pactl", "set-source-volume", "@DEFAULT_SOURCE@", f"{vol_percent}%"], check=True)
        # Ensure not muted
        subprocess.run(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "0"], capture_output=True)

        # Unmute & max hardware ALSA controls
        for control in ["Capture", "Mic", "Internal Mic", "Digital", "Boost", "Mic Boost", "Input"]:
            subprocess.run(["amixer", "sset", control, "100%"], capture_output=True)
            subprocess.run(["amixer", "sset", control, "unmute"], capture_output=True)
            subprocess.run(["amixer", "sset", control, "cap"], capture_output=True)
        return True
    except Exception as e:
        print(f"⚠️ Failed to set volume: {e}")
        return False


def ensure_speaker_loud():
    """Ensure speaker sink is unmuted and set to 100%."""
    try:
        subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"], capture_output=True)
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], capture_output=True)
        subprocess.run(["amixer", "sset", "Master", "100%"], capture_output=True)
        subprocess.run(["amixer", "sset", "Master", "unmute"], capture_output=True)
    except Exception:
        pass


def load_mic_config():
    if MIC_CONFIG_FILE.exists():
        try:
            return json.loads(MIC_CONFIG_FILE.read_text())
        except Exception:
            pass
    return {
        "source_volume_percent": 200,
        "energy_threshold": 60,
        "dynamic_energy_ratio": 1.25,
        "phrase_threshold": 0.15
    }


def save_mic_config(cfg):
    MIC_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    MIC_CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    print(f"\n💾 Saved mic config to {MIC_CONFIG_FILE}!")


def continuous_loop_calibration(cfg):
    """
    Loop:
    1. Records 3 seconds
    2. Plays it back immediately over speaker at 100%
    3. Asks you: [+][-][s][q] to adjust gain in real-time
    """
    clear_screen()
    print("=" * 65)
    print("🔁 CONTINUOUS LISTEN & PLAYBACK LOOP")
    print("=" * 65)
    print("How it works:")
    print("  • Records 3 seconds of audio from your microphone")
    print("  • Plays it right back to you through the speaker at 100% volume")
    print("  • You choose to Increase (+), Decrease (-), or Save (s)")
    print("=" * 65)

    test_wav = Path("/tmp/rk_loop_test.wav")

    while True:
        current_vol = get_pactl_volume()
        ensure_speaker_loud()

        print(f"\n🎤 Current Mic Gain: \033[96m{current_vol}%\033[0m")
        print("👉 Speak now (3 seconds test recording)...")
        time.sleep(0.4)

        # Record via arecord mapped through pulse to get full boosted volume
        try:
            subprocess.run([
                "arecord", "-D", "pulse", "-r", "16000", "-c", "1",
                "-f", "S16_LE", "-d", "3", "-q", str(test_wav)
            ], check=True)
        except Exception:
            try:
                subprocess.run([
                    "arecord", "-D", "default", "-r", "16000", "-c", "1",
                    "-f", "S16_LE", "-d", "3", "-q", str(test_wav)
                ], check=True)
            except Exception:
                # Fallback to speech_recognition if arecord directly fails
                r = sr.Recognizer()
                with sr.Microphone(sample_rate=16000) as source:
                    audio = r.record(source, duration=3)
                with open(test_wav, "wb") as f:
                    f.write(audio.get_wav_data())

        # Measure audio metrics
        peak = 0
        rms = 0
        try:
            import audioop
            data = test_wav.read_bytes()
            if len(data) > 44:
                raw = data[44:]
                peak = audioop.max(raw, 2)
                rms = audioop.rms(raw, 2)
        except Exception:
            pass

        print(f"📊 Capture metrics: RMS={rms} | Peak={peak}/32767", end=" ")
        if peak > 30000:
            print("\033[91m(⚠️ CLIPPING / DISTORTED - REDUCE GAIN)\033[0m")
        elif peak < 3000:
            print("\033[93m(⚠️ TOO QUIET - INCREASE GAIN)\033[0m")
        else:
            print("\033[92m(✅ GOOD AUDIO RANGE)\033[0m")

        # Instant Playback at 100%
        print("🔊 Playing back through speaker at 100%...")
        ensure_speaker_loud()
        subprocess.run(["aplay", "-q", str(test_wav)])

        # Single-prompt adjustment
        print("-" * 65)
        print("Actions: [+] +25% | [-] -25% | [number] e.g. 250 | [r] Retry | [s] Save & Exit | [q] Cancel")
        choice = input("Your choice: ").strip().lower()

        if choice in ("+", "="):
            new_v = min(500, current_vol + 25)
            set_pactl_volume(new_v)
            cfg["source_volume_percent"] = new_v
        elif choice in ("-", "_"):
            new_v = max(20, current_vol - 25)
            set_pactl_volume(new_v)
            cfg["source_volume_percent"] = new_v
        elif choice.isdigit():
            new_v = max(10, min(500, int(choice)))
            set_pactl_volume(new_v)
            cfg["source_volume_percent"] = new_v
            print(f"Gain set directly to {new_v}%")
        elif choice == "s":
            cfg["source_volume_percent"] = current_vol
            save_mic_config(cfg)
            input("Press Enter to return to main menu...")
            break
        elif choice == "q":
            break


def live_vu_meter(duration_sec=10):
    """Shows a live ASCII VU volume meter so you can see background noise vs speaking."""
    print(f"\n📊 Live Audio VU Meter running for {duration_sec}s (Speak now to see levels)...")
    print("Press Ctrl+C to stop early.\n")

    r = sr.Recognizer()
    with sr.Microphone(sample_rate=16000) as source:
        start = time.time()
        try:
            while time.time() - start < duration_sec:
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

                bars = min(40, int(rms / 120))
                meter = "█" * bars + "░" * (40 - bars)

                if peak > 28000:
                    status = "\033[91m🔥 CLIPPING / TOO LOUD\033[0m"
                elif rms > 300:
                    status = "\033[92m🗣️ VOICE DETECTED\033[0m"
                else:
                    status = "\033[90m💤 SILENCE / AMBIENT\033[0m"

                sys.stdout.write(f"\r[{meter}] RMS: {rms:5d} | Peak: {peak:5d}  {status}   ")
                sys.stdout.flush()
                time.sleep(0.04)
        except KeyboardInterrupt:
            pass
    print("\n")


def test_recording_and_stt(energy_threshold=35):
    r = sr.Recognizer()
    r.energy_threshold = energy_threshold
    r.dynamic_energy_threshold = True
    r.dynamic_energy_ratio = 1.3
    r.phrase_threshold = 0.15

    print(f"\n🎙️ Recording Test (Energy Threshold = {energy_threshold})...")
    print("👉 Speak a phrase now (e.g. 'Hello RK what is the weather?')...")

    with sr.Microphone(sample_rate=16000) as source:
        r.adjust_for_ambient_noise(source, duration=0.8)
        print(f"   [Calibrated Threshold]: {r.energy_threshold:.1f}")
        try:
            audio = r.listen(source, timeout=6, phrase_time_limit=5)
        except sr.WaitTimeoutError:
            print("⚠️ No speech detected (Timed out).")
            return None

    test_wav = Path("/tmp/rk_mic_tuning.wav")
    with open(test_wav, "wb") as f:
        f.write(audio.get_wav_data())

    try:
        import audioop
        raw = audio.get_raw_data()
        rms = audioop.rms(raw, 2)
        peak = audioop.max(raw, 2)
        print(f"   [Captured Audio]: RMS={rms} | Peak={peak}/32767")
    except Exception:
        pass

    print("\n   [Google STT Transcription]:")
    try:
        transcription = r.recognize_google(audio, language="en-IN").strip()
        print(f"   ✅ Recognized: \"{transcription}\"")
    except sr.UnknownValueError:
        print("   ⚠️ Audio was captured, but speech was unclear or noise.")
    except Exception as e:
        print(f"   ❌ STT Error: {e}")

    # Offer Gemini 3.5 Transcribe
    try:
        gemini_ans = input("\n🤖 Transcribe this recording with Gemini 3.5 Transcribe? (y/N): ").strip().lower()
        if gemini_ans == "y":
            test_gemini_35_transcribe(test_wav)
    except Exception:
        pass

    try:
        play_ans = input("\n🔊 Play back this recording through speaker at 100% volume? (y/N): ").strip().lower()
        if play_ans == "y":
            ensure_speaker_loud()
            print("🔊 Playing back through speaker at 100% volume...")
            subprocess.run(["aplay", "-q", str(test_wav)])
    except Exception:
        pass

    return test_wav



# ─── Google Gemini 3.5 Transcribe Integration ────────────────────────────────
def get_gemini_api_key():
    """Retrieve Gemini API key from environment or .env."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    for env_path in [BASE_DIR / ".env", BASE_DIR.parent / ".env"]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    k = line.split("=", 1)[1].strip(" '\"")
                    if k:
                        return k
    return ""


def test_gemini_35_transcribe(audio_wav_path: Path):
    """
    Transcribes audio using Google Gemini 3.5 Transcribe:
    - Model: 'gemini-3.5-transcribe'
    - Fallback: 'gemini-2.5-flash'
    """
    api_key = get_gemini_api_key()
    if not api_key:
        api_key = input("🔑 Enter GEMINI_API_KEY: ").strip()
        if not api_key:
            print("⚠️ No Gemini API Key provided.")
            return

    print("🤖 [Gemini 3.5 Transcribe] Uploading audio to Gemini API...")
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        audio_file = client.files.upload(file=str(audio_wav_path))

        print("🧠 [Gemini 3.5 Transcribe] Model: 'gemini-3.5-transcribe' processing...")
        response = client.models.generate_content(
            model="gemini-3.5-transcribe",
            contents=[audio_file],
        )
        transcription = (response.text or "").strip()
        print(f"✨ [Gemini 3.5 Transcribe Result]: '{transcription}'")
        return transcription
    except ImportError:
        print("❌ google-genai SDK not installed. Run: pip install google-genai")
    except Exception as e:
        print(f"⚠️ Gemini 3.5 Transcribe notice: {e}")
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            audio_file = client.files.upload(file=str(audio_wav_path))
            print("🔄 Retrying with gemini-2.5-flash audio transcription...")
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[audio_file, "Transcribe this speech recording word-for-word. Output only the transcribed text."]
            )
            transcription = (response.text or "").strip()
            print(f"✨ [Gemini Result]: '{transcription}'")
            return transcription
        except Exception as e2:
            print(f"❌ Gemini Error: {e2}")
    return None


def live_gemini_35_stream_transcribe():
    """
    ⚡ Real-Time Streaming Live Transcription using gemini-3.5-transcribe-live
    Streams microphone PCM frames directly over WebSocket connection.
    """
    api_key = get_gemini_api_key()
    if not api_key:
        api_key = input("🔑 Enter GEMINI_API_KEY: ").strip()
        if not api_key:
            print("⚠️ No Gemini API Key provided.")
            return

    try:
        import asyncio
        from google import genai
        from google.genai import types
    except ImportError:
        print("❌ google-genai SDK not installed. Run: pip install google-genai")
        return

    print("=" * 65)
    print("⚡ GEMINI 3.5 TRANSCRIBE LIVE — REAL-TIME MICROPHONE STREAMING")
    print("   Model: 'gemini-3.5-transcribe-live'")
    print("   Press Ctrl+C to stop streaming.")
    print("=" * 65)

    client = genai.Client(api_key=api_key)
    config = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        input_audio_transcription=types.AudioTranscriptionConfig(
            language_codes=["en-IN", "en-US"],
        ),
    )

    CHUNK_BYTES = 1024 * 2
    arecord_cmd = [
        "arecord", "-D", "pulse", "-f", "S16_LE", "-r", "16000", "-c", "1", "-q", "-t", "raw"
    ]
    try:
        proc = subprocess.Popen(arecord_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception:
        arecord_cmd[2] = "default"
        proc = subprocess.Popen(arecord_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    async def _stream_loop():
        async with client.aio.live.connect(model="gemini-3.5-transcribe-live", config=config) as session:
            print("🟢 Connected to Gemini Live! Speak now...\n")

            async def send_mic():
                while proc.poll() is None:
                    chunk = await asyncio.to_thread(proc.stdout.read, CHUNK_BYTES)
                    if not chunk:
                        break
                    await session.send_realtime_input(
                        audio=types.Blob(
                            data=chunk,
                            mime_type="audio/pcm;rate=16000"
                        )
                    )
                    await asyncio.sleep(0.01)

            async def recv_transcription():
                async for response in session.receive():
                    server_content = getattr(response, "server_content", None)
                    if server_content is not None:
                        model_turn = getattr(server_content, "model_turn", None)
                        if model_turn is not None:
                            for part in model_turn.parts:
                                if hasattr(part, "text") and part.text:
                                    print(part.text, end="", flush=True)

            s_task = asyncio.create_task(send_mic())
            r_task = asyncio.create_task(recv_transcription())
            await asyncio.gather(s_task, r_task)

    try:
        asyncio.run(_stream_loop())
    except KeyboardInterrupt:
        print("\n⏹️ Stopped Gemini Live Stream.")
    except Exception as e:
        print(f"\n⚠️ Gemini Live Stream: {e}")
    finally:
        if proc:
            proc.terminate()

def main():
    cfg = load_mic_config()

    while True:
        clear_screen()
        current_vol = get_pactl_volume()
        print("=" * 65)
        print("🎛️  RK AI Assistant — Interactive Microphone Tuning Studio")
        print("=" * 65)
        print(f" Current Mic Capture Gain (PulseAudio) : \033[96m{current_vol}%\033[0m")
        print(f" Base Energy Detection Threshold       : {cfg.get('energy_threshold', 35)}")
        print("=" * 65)
        print(" [c] 🔁 Continuous Listen & Playback Loop (Auto-record & hear at 100%)")
        print(" [v] 📊 Live VU Meter (See background noise vs speech levels)")
        print(" [t] 🎙️ Test Speech & Google STT Transcription")
        print(" [g] 🤖 Test Gemini 3.5 Transcribe (File Model)")
        print(" [l] ⚡ Gemini 3.5 Transcribe Live (Real-Time Mic Stream)")
        print(" [+] 🔊 Increase Mic Gain (+15%)")
        print(" [-] 🔉 Decrease Mic Gain (-15%)")
        print(" [e] ⚙️  Change Energy Threshold manually")
        print(" [s] 💾 Save Settings for RK Assistant")
        print(" [q] 🚪 Quit")
        print("=" * 65)

        choice = input("\nSelect an option: ").strip().lower()

        if choice == "c":
            continuous_loop_calibration(cfg)
        elif choice == "v":
            live_vu_meter(10)
            input("Press Enter to continue...")
        elif choice == "t":
            test_recording_and_stt(cfg.get("energy_threshold", 35))
            input("\nPress Enter to return to menu...")
        elif choice == "g":
            wav = test_recording_and_stt(cfg.get("energy_threshold", 35))
            if wav:
                test_gemini_35_transcribe(wav)
            input("\nPress Enter to return to menu...")
        elif choice == "l":
            live_gemini_35_stream_transcribe()
            input("\nPress Enter to return to menu...")
        elif choice in ("+", "="):
            new_v = min(250, current_vol + 15)
            set_pactl_volume(new_v)
            cfg["source_volume_percent"] = new_v
        elif choice in ("-", "_"):
            new_v = max(20, current_vol - 15)
            set_pactl_volume(new_v)
            cfg["source_volume_percent"] = new_v
        elif choice == "e":
            val = input(f"Enter new Energy Threshold (current: {cfg.get('energy_threshold', 35)}): ").strip()
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
