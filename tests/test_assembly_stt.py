import pyaudio
import websocket
import json
import threading
import time
import wave
from urllib.parse import urlencode
from datetime import datetime

# Replace with your chosen API key, this is the "default" account api key
API_KEY = "b59508f5369746ddae9b01fc792c2058"
CONNECTION_PARAMS = {
    "sample_rate": 16000,
    "format_turns": "true" 
}
API_ENDPOINT_BASE_URL = "wss://streaming.assemblyai.com/v3/ws"
API_ENDPOINT = f"{API_ENDPOINT_BASE_URL}?{urlencode(CONNECTION_PARAMS)}"

# Audio Configuration
FRAMES_PER_BUFFER = 800  # 50ms of audio (0.05s * 16000Hz)
SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16

# Global variables for audio stream and websocket
audio = None
stream = None
ws_app = None
audio_thread = None
stop_event = threading.Event()  # To signal the audio thread to stop

# WAV recording variables
recorded_frames = []  # Store audio frames for WAV file
recording_lock = threading.Lock()  # Thread-safe access to recorded_frames
start_time = None

# --- WebSocket Event Handlers ---

def on_open(ws):
    """Called when the WebSocket connection is established."""
    print("WebSocket connection opened.")
    print(f"Connected to: {API_ENDPOINT}")
    global start_time
    # Start sending audio data in a separate thread
    def stream_audio():
        global stream, start_time
        print("Starting audio streaming...")
        start_time = time.time()
        while not stop_event.is_set():
            try:
                audio_data = stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False)

                # Store audio data for WAV recording
                with recording_lock:
                    recorded_frames.append(audio_data)

                # Send audio data as binary message
                ws.send(audio_data, websocket.ABNF.OPCODE_BINARY)
            except Exception as e:
                print(f"Error streaming audio: {e}")
                # If stream read fails, likely means it's closed, stop the loop
                break
        print("Audio streaming stopped.")

    global audio_thread
    audio_thread = threading.Thread(target=stream_audio)
    audio_thread.daemon = (
        True  # Allow main thread to exit even if this thread is running
    )
    audio_thread.start()

def on_message(ws, message):
    try:
        data = json.loads(message)
        # print(f"DEBUG RAW: {message}") # Uncomment if needed
        
        msg_type = data.get('message_type') # AssemblyAI v2 uses message_type
        # User code used msg_type = data.get('type')
        # Let's stick to user code but add debugging
        if not msg_type:
             msg_type = data.get('message_type')

        text = data.get('text')
        
        if msg_type == "FinalTranscript":
            end_time = time.time()
            latency = (end_time - start_time) if start_time else 0
            print(f"\n[AssemblyAI] Final: {text} (Latency: {latency:.2f}s)")
        elif msg_type == "PartialTranscript":
            print(f"\r[AssemblyAI] Partial: {text}", end="")
            
    except json.JSONDecodeError as e:
        print(f"Error decoding message: {e}")
    except Exception as e:
        print(f"Error handling message: {e}")

def on_error(ws, error):
    """Called when a WebSocket error occurs."""
    print(f"\nWebSocket Error: {error}")
    # Attempt to signal stop on error
    stop_event.set()

def on_close(ws, close_status_code, close_msg):
    """Called when the WebSocket connection is closed."""
    print(f"\nWebSocket Disconnected: Status={close_status_code}, Msg={close_msg}")

    # Save recorded audio to WAV file
    save_wav_file()

    # Ensure audio resources are released
    global stream, audio
    stop_event.set()  # Signal audio thread just in case it's still running

    if stream:
        if stream.is_active():
            stream.stop_stream()
        stream.close()
        stream = None
    if audio:
        audio.terminate()
        audio = None

def save_wav_file():
    """Save recorded audio frames to a WAV file."""
    if not recorded_frames:
        print("No audio data recorded.")
        return

    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"assembly_recorded_{timestamp}.wav"

    try:
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit = 2 bytes
            wf.setframerate(SAMPLE_RATE)

            # Write all recorded frames
            with recording_lock:
                wf.writeframes(b''.join(recorded_frames))

        print(f"Audio saved to: {filename}")
        print(f"Duration: {len(recorded_frames) * FRAMES_PER_BUFFER / SAMPLE_RATE:.2f} seconds")

    except Exception as e:
        print(f"Error saving WAV file: {e}")

# --- Main Execution ---
def run():
    global audio, stream, ws_app
    audio = pyaudio.PyAudio()

    # List Microphones
    info = audio.get_host_api_info_by_index(0)
    numdevices = info.get('deviceCount')
    device_idx = None
    print("\n--- Available Microphones ---")
    for i in range(0, numdevices):
        if (audio.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
            name = audio.get_device_info_by_host_api_device_index(0, i).get('name')
            print(f"Input Device id {i} - {name}")
            if "USB" in name:
                device_idx = i
    
    if device_idx is None:
        device_idx = 1 # Fallback to 1 on Pi usually
        print(f"No USB mic found, defaulting to index {device_idx}")
    else:
        print(f"Auto-selected USB Device: index {device_idx}")

    # Open microphone stream
    try:
        stream = audio.open(
            input=True,
            frames_per_buffer=FRAMES_PER_BUFFER,
            channels=CHANNELS,
            format=FORMAT,
            rate=SAMPLE_RATE,
            input_device_index=device_idx
        )
        print("Microphone stream opened successfully.")
        print("Speak into your microphone. Press Ctrl+C to stop.")
        print("Audio will be saved to a WAV file when the session ends.")
    except Exception as e:
        print(f"Error opening microphone stream: {e}")
        if audio:
            audio.terminate()
        return  # Exit if microphone cannot be opened

    # Create WebSocketApp
    ws_app = websocket.WebSocketApp(
        API_ENDPOINT,
        header={"Authorization": API_KEY},
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    # Run WebSocketApp in a separate thread to allow main thread to catch KeyboardInterrupt
    ws_thread = threading.Thread(target=ws_app.run_forever)
    ws_thread.daemon = True
    ws_thread.start()

    try:
        # Keep main thread alive until interrupted
        while ws_thread.is_alive():
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nCtrl+C received. Stopping...")
        stop_event.set()  # Signal audio thread to stop
        ws_app.close()
        ws_thread.join(timeout=2.0)

if __name__ == "__main__":
    run()
