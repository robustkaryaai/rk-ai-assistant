import requests
from .config import BACKEND_BASE_URL, RK_WEBHOOK_SECRET

def trigger_desktop_action(intent: str, parameters: dict = None, slug: str = "000000000"):
    """
    Relay a command to the Desktop Agent via the Backend's real-time relay.
    """
    url = f"{BACKEND_BASE_URL}/device/{slug}/to-desktop"
    headers = {}
    if RK_WEBHOOK_SECRET:
        headers["X-RK-Webhook-Secret"] = RK_WEBHOOK_SECRET
    
    try:
        # Standard HTTP POST to the relay endpoint
        # The backend then pushes this via SSE to the connected Desktop Agent
        response = requests.post(url, json={
            "intent": intent,
            "parameters": parameters or {}
        }, headers=headers, timeout=5)
        
        if response.ok:
            print(f"[DesktopLink] Command '{intent}' relayed successfully via Cloud.")
            return True
        else:
            print(f"[DesktopLink] Cloud relay failed: {response.text}")
            return False
    except Exception as e:
        print(f"[DesktopLink] Relay error: {e}")
        return False
