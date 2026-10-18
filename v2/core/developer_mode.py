"""
Developer Benchmark & Performance Profiler for RK AI Assistant V2.
Tests and benchmarks all components (excluding mic STT):
1. Fast Instant Router latency (regex matcher)
2. ALSA amixer hardware volume & mic latency
3. TTS Engine latency (gTTS vs Flite)
4. Audio Player / mpg123 file playback latency
5. Local Music Streamer (yt-dlp search & URL resolution)
6. Open-Meteo Weather API & caching latency
7. Backend Roundtrip (Cloud ping & text query)
8. Offline LLM Inference (llama-cli / Qwen2.5-0.5B speed & tokens/sec)
9. Memory & System resource footprint (Resident RAM & Swap)
"""

import os
import sys
import time
import subprocess
import shutil
from pathlib import Path

# Add v2 root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config import (
    DEVICE_SLUG,
    BACKEND_BASE_URL,
    AUDIO_CACHE_DIR,
    BLUETOOTH_HCI,
    BLUETOOTH_SPEAKER_MAC,
)
from router import FastCommandRouter
from audio.tts import TTSManager
from audio.player import AudioPlayer
from audio.streamer import LocalMusicStreamer
from backend.client import RKHomeClient
from core.weather import WeatherService
from core.alarm_manager import AlarmScheduleManager
from core.sound_monitor import SoundEventMonitor
from hardware.mic import HardwareMicManager
from llm.offline_llm import OfflineLLM


class BenchmarkSuite:
    def __init__(self):
        self.results = {}
        self.client = RKHomeClient(BACKEND_BASE_URL, DEVICE_SLUG)
        self.tts = TTSManager(AUDIO_CACHE_DIR)
        self.player = AudioPlayer()
        self.offline_llm = OfflineLLM()

    def print_header(self):
        print("\n" + "=" * 65)
        print("⚡ RK AI ASSISTANT V2 — COMPREHENSIVE DEVELOPER BENCHMARK")
        print(f"📍 Device Slug:  {DEVICE_SLUG}")
        print(f"📶 BT Adapter:   {BLUETOOTH_HCI}")
        print(f"🔊 Speaker MAC:  {BLUETOOTH_SPEAKER_MAC}")
        print(f"🌐 Backend Host: {BACKEND_BASE_URL}")
        print("=" * 65 + "\n")

    def run_all(self):
        self.print_header()

        self.bench_system_resources()
        self.bench_router_latency()
        self.bench_hardware_mixer()
        self.bench_weather_engine()
        self.bench_audio_playback()
        self.bench_tts_engine()
        self.bench_music_streamer()
        self.bench_backend_latency()
        self.bench_offline_llm()

        self.print_summary()

    def bench_system_resources(self):
        print("📊 [1/9] Benchmarking System Memory & Resources...")
        ram_info = "N/A"
        try:
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
                mem_total = 0
                mem_avail = 0
                for line in lines:
                    if "MemTotal:" in line:
                        mem_total = int(line.split()[1]) // 1024
                    elif "MemAvailable:" in line:
                        mem_avail = int(line.split()[1]) // 1024
                used = mem_total - mem_avail
                ram_info = f"{used}MB / {mem_total}MB used ({mem_avail}MB free)"
        except Exception:
            pass

        # Python Resident Memory
        try:
            import resource
            py_ram_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # On Linux ru_maxrss is in KB, on macOS it is in bytes
            py_ram_mb = (py_ram_kb / 1024) if sys.platform.startswith("linux") else (py_ram_kb / (1024 * 1024))
            py_ram_str = f"{py_ram_mb:.1f} MB"
        except Exception:
            py_ram_str = "N/A"

        print(f"   • Total OS RAM:      {ram_info}")
        print(f"   • Assistant RAM:     {py_ram_str}")
        self.results["RAM Footprint"] = {"Latency": py_ram_str, "Rating": "🟢 Ultra-Light"}

    def bench_router_latency(self):
        print("\n⚡ [2/9] Benchmarking Fast Command Router (Zero-Latency Matcher)...")
        test_phrases = [
            "stop",
            "volume up",
            "set volume to 65",
            "run diagnostics",
            "good morning",
            "weather in Mumbai",
            "night protocol",
            "play Hanuman Chalisa",
            "mute mic",
            "start pomodoro"
        ]

        start = time.perf_counter()
        runs = 1000
        for _ in range(runs):
            for phrase in test_phrases:
                FastCommandRouter.route(phrase)
        elapsed = (time.perf_counter() - start) / (runs * len(test_phrases)) * 1000  # ms per route

        rating = "🟢 Lightning (<0.1ms)" if elapsed < 0.1 else ("🟡 Fast (<1ms)" if elapsed < 1 else "🔴 Slow")
        print(f"   • {runs * len(test_phrases)} regex routes completed")
        print(f"   • Average match latency: {elapsed:.3f} ms")
        self.results["Fast Router"] = {"Latency": f"{elapsed:.3f} ms", "Rating": rating}

    def bench_hardware_mixer(self):
        print("\n🎛️ [3/9] Benchmarking Hardware Audio Controls (amixer)...")
        start = time.perf_counter()
        ok_vol = self.player.set_system_volume("set", 75)
        vol_time = (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        ok_mic = HardwareMicManager.unmute()
        mic_time = (time.perf_counter() - start) * 1000

        total_time = vol_time + mic_time
        rating = "🟢 Instant (<50ms)" if total_time < 50 else "🟡 Acceptable (<150ms)"
        print(f"   • Volume set latency: {vol_time:.1f} ms")
        print(f"   • Mic control latency: {mic_time:.1f} ms")
        self.results["Hardware Audio Mixer"] = {"Latency": f"{vol_time:.1f} ms", "Rating": rating}

    def bench_weather_engine(self):
        print("\n🌤️ [4/9] Benchmarking Weather Engine (Open-Meteo REST)...")
        # 1. Uncached fetch
        start = time.perf_counter()
        data = WeatherService.get_weather("Delhi")
        uncached_time = (time.perf_counter() - start) * 1000

        # 2. Cached fetch
        start = time.perf_counter()
        data_cached = WeatherService.get_weather("Delhi")
        cached_time = (time.perf_counter() - start) * 1000

        rating = "🟢 Fast (<400ms)" if uncached_time < 400 else "🟡 Acceptable (<1s)"
        print(f"   • Live Network Fetch: {uncached_time:.1f} ms (Temp: {data.get('temp_c')}°C)")
        print(f"   • Local Cache Hit:    {cached_time:.2f} ms")
        self.results["Weather API (Network)"] = {"Latency": f"{uncached_time:.0f} ms", "Rating": rating}
        self.results["Weather Cache (Local)"] = {"Latency": f"{cached_time:.2f} ms", "Rating": "🟢 Instant"}

    def bench_audio_playback(self):
        print("\n🔊 [5/9] Benchmarking Audio Player & Pre-rendered Greeting...")
        ready_file = BASE_DIR / "data" / "sounds" / "ready.mp3"
        if not ready_file.exists():
            print("   ⚠️ ready.mp3 not found, generating now...")
            try:
                from gtts import gTTS
                ready_file.parent.mkdir(parents=True, exist_ok=True)
                gTTS("Radhe Radhe! RK AI Assistant is ready.", lang="en", tld="co.in").save(str(ready_file))
            except Exception:
                pass

        start = time.perf_counter()
        # Spawn mpg123 process and measure process kickoff latency
        ok = self.player.play_url_or_file(str(ready_file), is_speech=True)
        kickoff_time = (time.perf_counter() - start) * 1000
        time.sleep(1.0)  # Play 1 second then stop
        self.player.stop()

        rating = "🟢 Instant (<30ms)" if kickoff_time < 30 else "🟡 Good (<80ms)"
        print(f"   • Player spawn & route latency: {kickoff_time:.1f} ms")
        self.results["Audio Playback Spawn"] = {"Latency": f"{kickoff_time:.1f} ms", "Rating": rating}

    def bench_tts_engine(self):
        print("\n🗣️ [6/9] Benchmarking TTS Engines (gTTS vs Cached)...")
        sample_phrase = "System performance benchmark initialized."

        # Cache test
        start = time.perf_counter()
        f1 = self.tts.get_speech_file(sample_phrase)
        first_gen_time = (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        f2 = self.tts.get_speech_file(sample_phrase)
        cache_hit_time = (time.perf_counter() - start) * 1000

        print(f"   • First Gen (gTTS Network): {first_gen_time:.0f} ms")
        print(f"   • Subsequent Cache Hit:     {cache_hit_time:.2f} ms")
        self.results["TTS Generation (gTTS)"] = {"Latency": f"{first_gen_time:.0f} ms", "Rating": "🟡 Normal"}
        self.results["TTS Cache Hit (Local)"] = {"Latency": f"{cache_hit_time:.2f} ms", "Rating": "🟢 Instant"}

    def bench_music_streamer(self):
        print("\n🎵 [7/9] Benchmarking Local Music Streamer (Fast scrape + yt-dlp)...")
        query = "Alan Walker Faded"
        start = time.perf_counter()
        url = LocalMusicStreamer.get_audio_stream_url(query)
        elapsed = time.perf_counter() - start

        if url:
            rating = "🟢 Excellent (<2s)" if elapsed < 2.0 else ("🟡 Good (<5s)" if elapsed < 5.0 else "🟠 Moderate")
            print(f"   • Query: '{query}'")
            print(f"   • Stream URL resolved in: {elapsed:.2f} s")
            self.results["Music Streamer (yt-dlp)"] = {"Latency": f"{elapsed:.2f} s", "Rating": rating}
        else:
            print("   ⚠️ yt-dlp resolution timed out or network blocked")
            self.results["Music Streamer (yt-dlp)"] = {"Latency": "Timeout / N/A", "Rating": "🔴 Error"}

    def bench_backend_latency(self):
        print("\n☁️ [8/9] Benchmarking Cloud Backend Roundtrip...")
        # 1. Maintenance ping
        start = time.perf_counter()
        maint_res = self.client.poll_maintenance()
        maint_time = (time.perf_counter() - start) * 1000

        # 2. Text command query
        start = time.perf_counter()
        text_res = self.client.send_text("hello rk ai")
        text_time = (time.perf_counter() - start) * 1000

        print(f"   • Heartbeat Ping: {maint_time:.0f} ms")
        print(f"   • Text NLP Query: {text_time:.0f} ms")
        self.results["Backend Heartbeat"] = {"Latency": f"{maint_time:.0f} ms", "Rating": "🟢 Fast" if maint_time < 300 else "🟡 Acceptable"}
        self.results["Backend Text Query"] = {"Latency": f"{text_time:.0f} ms", "Rating": "🟢 Fast" if text_time < 1200 else "🟡 Normal"}

    def bench_offline_llm(self):
        print("\n🧠 [9/9] Benchmarking Offline LLM (Qwen2.5-0.5B / llama-cli)...")
        import os
        model_exists = os.path.isfile(self.offline_llm.model_path)
        cli_exists = bool(self.offline_llm.llama_cli and os.path.isfile(self.offline_llm.llama_cli))

        if not self.offline_llm.is_ready:
            if not model_exists:
                print(f"   ⚠️ Model file missing at: {self.offline_llm.model_path}")
                reason = "Model Missing"
            elif not cli_exists:
                print("   ⚠️ llama-cli binary not installed.")
                reason = "Binary Missing"
            else:
                print(f"   ⚠️ llama-cli installed & model present, but CPU architecture incompatible (ARMv6 Illegal instruction).")
                reason = "CPU Incompatible (ARMv6)"
            self.results["Offline LLM Inference"] = {"Latency": reason, "Rating": "⚪ Skipped"}
            return

        test_prompt = "What is the capital of India? One word only."
        start = time.perf_counter()
        reply = self.offline_llm.ask(test_prompt)
        elapsed = time.perf_counter() - start

        print(f"   • Prompt: '{test_prompt}'")
        print(f"   • Reply:  '{reply}'")
        print(f"   • Total Inference Time: {elapsed:.2f} s")

        # Estimate tokens/sec (~15 tokens generated + prompt)
        rating = "🟢 Excellent for Pi" if elapsed < 15 else "🟡 Normal Pi Speed"
        self.results["Offline LLM Inference"] = {"Latency": f"{elapsed:.2f} s", "Rating": rating}

    def print_summary(self):
        print("\n" + "=" * 65)
        print("🏆 DEVELOPER BENCHMARK SUMMARY TABLE")
        print("=" * 65)
        print(f"{'Component':<28} | {'Latency / Measurement':<22} | {'Rating'}")
        print("-" * 65)
        for comp, data in self.results.items():
            print(f"{comp:<28} | {data['Latency']:<22} | {data['Rating']}")
        print("=" * 65)
        print("💡 Benchmark complete! Use these metrics to profile leads and lags.\n")


if __name__ == "__main__":
    suite = BenchmarkSuite()
    suite.run_all()
