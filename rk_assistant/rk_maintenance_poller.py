import time
import requests
import sys
from threading import Thread, Lock

# Try to use correct paths dynamically
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from rk_assistant.config import BACKEND_BASE_URL
from rk_assistant.networking import read_slug

_poller_thread = None
_poller_lock = Lock()

def run_poller():
    print("[maintenance] Standalone poller starting...")
    while True:
        try:
            slug_val, _ = read_slug()
            if slug_val:
                url = f"{BACKEND_BASE_URL}/device/{slug_val}/maintenance"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    print(f"[maintenance] Successfully pinged maintenance logic for {slug_val}")
                else:
                    print(f"[maintenance] Ping failed for {slug_val} with status {resp.status_code}")
            else:
                print("[maintenance] Slug not found yet, skipping cycle.")
        except Exception as e:
            print(f"[maintenance] Error pinging backend: {e}")
            
        time.sleep(45) # Ping every 45s for Shoom stability

def start_maintenance_poller() -> None:
    """Start the background maintenance polling loop once."""
    global _poller_thread
    with _poller_lock:
        if _poller_thread and _poller_thread.is_alive():
            print("[maintenance] Maintenance poller already running, skipping start.")
            return

        _poller_thread = Thread(target=run_poller, daemon=True)
        _poller_thread.start()
        print("[maintenance] Background maintenance poller started")

if __name__ == "__main__":
    run_poller()
