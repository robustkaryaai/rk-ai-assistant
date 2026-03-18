import time
import requests
import sys

# Try to use correct paths dynamically
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from rk_assistant.config import BACKEND_BASE_URL
from rk_assistant.networking import read_slug

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

if __name__ == "__main__":
    run_poller()
