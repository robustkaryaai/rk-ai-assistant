import speech_recognition as sr
import time
import os

def benchmark_google():
    r = sr.Recognizer()
    mic = sr.Microphone()
    
    print("="*40)
    print("GOOGLE STT BENCHMARK")
    print("="*40)
    
    with mic as source:
        print("Calibrating (1s)...")
        r.adjust_for_ambient_noise(source, duration=1.0)
        print("Speak NOW (Recording for 5 seconds)...")
        
        start_rec = time.time()
        try:
            audio = r.listen(source, timeout=5, phrase_time_limit=5)
            end_rec = time.time()
            print("Recording complete.")
            
            print("Sending to Google...")
            start_transcribe = time.time()
            text = r.recognize_google(audio)
            end_transcribe = time.time()
            
            latency = end_transcribe - start_transcribe
            total_time = end_transcribe - start_rec
            
            print(f"\n[Google] Result: {text}")
            print(f"Transcribe Latency: {latency:.2f}s")
            print(f"Total Time (Rec+Trans): {total_time:.2f}s")
            
        except sr.WaitTimeoutError:
            print("No speech detected.")
        except sr.UnknownValueError:
            print("Could not understand audio.")
        except sr.RequestError as e:
            print(f"Google API Error: {e}")

if __name__ == "__main__":
    benchmark_google()
