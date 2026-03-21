"""
RexyCore Desktop Link (Hub to Desktop)
Handles WebSocket communication from the Assistant Hub to the Desktop Agent.
"""

import asyncio
import json
import websockets
import os

DESKTOP_IP = os.getenv("DESKTOP_IP", "localhost")  # User can set in .env
DESKTOP_PORT = 8765

async def send_desktop_command(intent: str, parameters: dict = None):
    """Send a command to the Desktop Agent via WebSocket."""
    uri = f"ws://{DESKTOP_IP}:{DESKTOP_PORT}"
    
    try:
        async with websockets.connect(uri, timeout=3) as websocket:
            command = {
                "type": "command",
                "intent": intent,
                "parameters": parameters or {}
            }
            await websocket.send(json.dumps(command))
            
            # Wait for ACK
            response = await websocket.recv()
            data = json.loads(response)
            if data.get("type") == "ack":
                print(f"[DesktopLink] Command '{intent}' executed successfully.")
                return True
    except Exception as e:
        print(f"[DesktopLink] Failed to send command to {uri}: {e}")
        return False

def trigger_desktop_action(intent: str, parameters: dict = None):
    """Synchronous wrapper to trigger a desktop action."""
    try:
        asyncio.run(send_desktop_command(intent, parameters))
    except Exception as e:
        print(f"[DesktopLink] Async error: {e}")
