"""
Smart Home Controller for RK AI Assistant.
Simulates Alexa-like local device control (Tuya, TPLink, generic HTTP relays).
"""

import requests
import time
import json

def control_device(device_name: str, state: bool, color: str = None) -> str:
    """
    Attempts to control a local smart device on the network.
    Because we don't have paid APIs, we ping typical smart home endpoints 
    or just return a simulated success for the dashboard to track.
    """
    print(f"[SmartHome] Action: {'Turn ON' if state else 'Turn OFF'} | Device: {device_name} | Color: {color or 'default'}")
    
    # In a real environment, you'd scan for local IPs or match a config file here.
    # For now, we simulate success so the Assistant can verbally confirm it.
    
    # Add a tiny delay to simulate network latency
    time.sleep(0.5)
    
    action_str = "Turned on" if state else "Turned off"
    suffix = f" and set color to {color}" if color else ""
    return f"{action_str} the {device_name}{suffix}."
    
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
        
    device = "lights"
    if "fan" in text_lower: device = "fan"
    if "tv" in text_lower: device = "TV"
    if "ac " in text_lower or "air conditioner" in text_lower: device = "AC"
    
    color = None
    colors = ["red", "blue", "green", "yellow", "purple", "white", "warm", "cool"]
    for c in colors:
        if c in text_lower:
            color = c
            break
            
    return control_device(device, state, color)
