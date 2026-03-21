import requests
import json
import os

BACKEND_BASE_URL = "https://rk-ai-backend.onrender.com"

def trigger_desktop_action(intent: str, parameters: dict = None, slug: str = "000000000"):
    """
    Relay a command to the Desktop Agent via the Backend's real-time relay.
    """
    url = f"{BACKEND_BASE_URL}/device/{slug}/to-desktop"
    
    try:
        # Standard HTTP POST to the relay endpoint
        # The backend then pushes this via SSE to the connected Desktop Agent
        response = requests.post(url, json={
            "intent": intent,
            "parameters": parameters or {}
        }, timeout=5)
        
        if response.ok:
            print(f"[DesktopLink] Command '{intent}' relayed successfully via Cloud.")
            return True
        else:
            print(f"[DesktopLink] Cloud relay failed: {response.text}")
            return False
    except Exception as e:
        print(f"[DesktopLink] Relay error: {e}")
        return False
