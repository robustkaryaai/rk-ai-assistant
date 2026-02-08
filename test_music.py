#!/usr/bin/env python3
"""
Test script for music playback.
Directly tests the music_manager without the full voice assistant.
"""
import sys
import time
from rk_assistant.music_manager import play_music

def main():
    print("=" * 50)
    print("RK AI Music Test")
    print("=" * 50)
    
    # Test with the song name
    song = "Sandeshe Aate Hain"
    print(f"\nTesting music playback: {song}")
    print("-" * 50)
    
    proc = play_music(song)
    
    if proc:
        print("\n✓ Music playback process started!")
        print("Waiting for music to play... (Press Ctrl+C to stop)")
        try:
            # Wait for the process to finish or user interrupt
            proc.wait()
            print("\n✓ Playback finished")
        except KeyboardInterrupt:
            print("\n\nStopping playback...")
            proc.terminate()
            proc.wait()
            print("✓ Stopped")
    else:
        print("\n✗ Failed to start music playback")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
