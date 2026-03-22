"""
Smart Home Controller for RK AI Assistant.
Reads the user's configured Wi-Fi appliances from Appwrite and sends local HTTP Webhooks.
"""

import requests
import time
import json
from .settings_sync import get_smart_devices

def control_device(device_name: str, state: bool, color: str = None) -> str:
    smart_devices = get_smart_devices()
    print(f"[SmartHome] Action: {'Turn ON' if state else 'Turn OFF'} | Spoken: {device_name} | Color: {color or 'default'}")
    
    device_name_lower = device_name.lower().strip()
    matched_device = None
    
    for d in smart_devices:
        db_name = str(d.get("name", "")).lower()
        if db_name in device_name_lower or device_name_lower in db_name:
            matched_device = d
            break
            
    if not matched_device:
        # Provide a general answer if the user hasn't configured any device with this name
        return f"I couldn't find a device named {device_name} in your Smart Home settings on the app."
    
    url = matched_device.get("on_url") if state else matched_device.get("off_url")
    if not url:
        return f"The {matched_device.get('name')} doesn't have a configured Web Hook U.R.L. for this action."
        
    try:
        res = requests.get(url, timeout=4)
        print(f"[SmartHome] Webhook executed: {res.status_code}")
        action_str = "Turned on" if state else "Turned off"
        suffix = f" and set color to {color}" if color else ""
        return f"{action_str} the {matched_device.get('name')}{suffix}."
    except Exception as e:
        print(f"[SmartHome] Request failed: {e}")
        return f"I tried to contact the {matched_device.get('name')}, but it didn't respond. Please check its connection."
    
def is_smart_home_intent(text: str) -> bool:
    text_lower = text.lower()
    
    if "turn on" in text_lower or "turn off" in text_lower or "switch" in text_lower:
        if any(w in text_lower for w in ["light", "bulb", "fan", "ac ", "tv"]):
            return True
            
    # Phrases like "lights out"
    if "lights out" in text_lower or "dim the lights" in text_lower:
        return True
        
    return False
    
def execute_smart_command(text: str) -> str:
    text_lower = text.lower()
    
    state = False
    if " on" in text_lower or "start" in text_lower:
        state = True
        
    device = "lights" # Fallback guess
    # Smarter extraction: "turn on the bedroom fan" -> "bedroom fan"
    words = text_lower.split()
    if "turn" in words:
        try:
            target_idx = words.index("the") + 1
            device = " ".join(words[target_idx:])
        except:
            if "fan" in text_lower: device = "fan"
            elif "tv" in text_lower: device = "TV"
            elif "ac " in text_lower or "air conditioner" in text_lower: device = "AC"
            elif "bulb" in text_lower or "light" in text_lower: device = "light"
    else:
        if "fan" in text_lower: device = "fan"
        elif "tv" in text_lower: device = "TV"
        elif "ac " in text_lower or "air conditioner" in text_lower: device = "AC"
        elif "bulb" in text_lower or "light" in text_lower: device = "light"

    # Color extraction (if applicable for smart bulbs)
    color = None
    colors = ["red", "blue", "green", "yellow", "purple", "white", "warm", "cool"]
    for c in colors:
        if c in text_lower:
            color = c
            break
            
    return control_device(device, state, color)
