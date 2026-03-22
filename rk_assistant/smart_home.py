"""
Smart Home Controller for RK AI Assistant.
Reads the user's configured Wi-Fi appliances from Appwrite and sends local HTTP Webhooks.
Includes discovery for TP-Link (Kasa/Tapo) and Yeelight LAN.
Xiaomi / Mi Home Wi-Fi bulbs: add manually in the RK app (IP + 32-char token) with type "miio".
Requires: pip install python-miio (same LAN as the Pi; token from Mi Cloud / extractor tools).
"""

import os
import requests
import time
import json
import asyncio
from .settings_sync import get_smart_devices

BACKEND_BASE_URL = os.getenv('BACKEND_BASE_URL', 'https://rk-ai-backend.onrender.com')


def _control_miio(ip: str, token: str, state: bool, model: str = None) -> None:
    """
    Control Xiaomi / Mi Home Wi-Fi devices using the local miio protocol.
    Token: 32 hex characters (no spaces), from device pairing / token tools.
    """
    from miio import Device  # pip install python-miio

    tok = token.replace(" ", "").strip().lower()
    if len(tok) != 32:
        raise ValueError("MiIO token must be exactly 32 hex characters")

    mdl = model.strip() if isinstance(model, str) and model.strip() else None
    dev = Device(ip, tok, model=mdl) if mdl else Device(ip, tok)
    power = "on" if state else "off"
    last = None
    for args in ([power], [power.upper()], [state]):
        try:
            dev.send("set_power", args)
            return
        except Exception as e:
            last = e
    if last:
        raise last


def discover_and_sync_devices(slug: str) -> dict:
    print("[SmartHome] Starting zero-config network discovery...")
    devices = []
    
    # 1. TP-Link Kasa / Tapo Discovery
    try:
        from kasa import Discover
        
        async def find_kasa():
            found = await Discover.discover()
            for ip, dev in found.items():
                await dev.update()
                devices.append({
                    "id": f"kasa_{dev.mac}",
                    "name": dev.alias,
                    "type": "kasa",
                    "ip": ip,
                    # Fallback URL for webhooks visually
                    "on_url": f"http://{ip}/on", 
                    "off_url": f"http://{ip}/off"
                })
        asyncio.run(find_kasa())
    except ImportError:
        print("[SmartHome] python-kasa not installed, skipping Tapo/Kasa discovery")
    except Exception as e:
        print(f"[SmartHome] Kasa discovery error: {e}")

    # 2. Yeelight Discovery
    try:
        from yeelight import discover_bulbs
        found = discover_bulbs()
        for i, dev in enumerate(found):
            devices.append({
                "id": f"yeelight_{dev.get('ip', i)}",
                "name": f"Yeelight Bulb {i+1}",
                "type": "yeelight",
                "ip": dev['ip'],
                "on_url": f"http://{dev['ip']}/on",
                "off_url": f"http://{dev['ip']}/off"
            })
    except ImportError:
        print("[SmartHome] yeelight not installed, skipping Yeelight discovery")
    except Exception as e:
        print(f"[SmartHome] Yeelight discovery error: {e}")

    # Deduplicate existing smart_devices manually configured by user
    existing = get_smart_devices()
    existing_ips = {d.get("ip") for d in existing if d.get("ip")}
    
    # Combine user configs with new discoveries
    final_devices = list(existing)
    for d in devices:
        if d["ip"] not in existing_ips:
            final_devices.append(d)

    # Sync back to Appwrite systemStatus via Backend
    print(f"[SmartHome] Scan complete. Found {len(devices)} native devices. Syncing {len(final_devices)} total...")
    try:
        res = requests.post(f"{BACKEND_BASE_URL}/device/{slug}/update-status", json={"smart_devices": final_devices}, timeout=10)
        return {"success": True, "count": len(devices), "devices": final_devices}
    except Exception as e:
        print(f"[SmartHome] Sync failed: {e}")
        return {"success": False, "error": str(e)}


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
        return f"I couldn't find a device named {device_name} in your Smart Home settings."
    
    dev_type = matched_device.get("type", "webhook")
    ip = matched_device.get("ip")
    
    try:
        # NATIVE KASA CONTROL
        if dev_type == "kasa" and ip:
            from kasa import SmartDevice
            async def toggle_kasa():
                dev = SmartDevice(ip)
                await dev.update()
                if state: await dev.turn_on()
                else: await dev.turn_off()
            asyncio.run(toggle_kasa())
            action_str = "Turned on" if state else "Turned off"
            return f"{action_str} the {matched_device.get('name')}."
            
        # NATIVE YEELIGHT CONTROL
        elif dev_type == "yeelight" and ip:
            from yeelight import Bulb
            bulb = Bulb(ip)
            if state: bulb.turn_on()
            else: bulb.turn_off()
            action_str = "Turned on" if state else "Turned off"
            return f"{action_str} the {matched_device.get('name')}."

        # XIAOMI / MI HOME (miio) — type "miio", fields: ip, token, optional miio_model
        elif dev_type in ("miio", "xiaomi", "mihome") and ip:
            token = matched_device.get("token") or matched_device.get("mi_token")
            if not token:
                return f"Add a 32-character Mi token for {matched_device.get('name')} in the RK app (Smart Hub)."
            try:
                _control_miio(ip, token, state, matched_device.get("miio_model"))
            except ImportError:
                return "python-miio is not installed on the hub. Run: pip install python-miio"
            action_str = "Turned on" if state else "Turned off"
            return f"{action_str} the {matched_device.get('name')}."
            
        # GENERIC WEBHOOK CONTROL
        else:
            url = matched_device.get("on_url") if state else matched_device.get("off_url")
            if not url:
                return f"The {matched_device.get('name')} doesn't have a configured URL for this action."
                
            res = requests.get(url, timeout=4)
            print(f"[SmartHome] Webhook executed: {res.status_code}")
            action_str = "Turned on" if state else "Turned off"
            suffix = f" and set color to {color}" if color else ""
            return f"{action_str} the {matched_device.get('name')}{suffix}."
            
    except Exception as e:
        print(f"[SmartHome] Request/Native Protocol failed: {e}")
        return f"I tried to contact the {matched_device.get('name')}, but it didn't respond. Please check its connection."
    
def is_smart_home_intent(text: str) -> bool:
    text_lower = text.lower()
    if "turn on" in text_lower or "turn off" in text_lower or "switch" in text_lower:
        if any(w in text_lower for w in ["light", "bulb", "fan", "ac ", "tv", "plug", "socket"]):
            return True
            
    if "lights out" in text_lower or "dim the lights" in text_lower:
        return True
        
    return False
    
def run_coding_ambience() -> str:
    """
    Turn on all paired smart devices for a coding session (bright workspace).
    Called before relaying Lumina / desktop actions to the PC.
    """
    devices = get_smart_devices()
    if not devices:
        return "No smart devices are paired yet. Pair lights in the RK app under Smart Hub, then try again."

    messages = []
    for d in devices:
        name = d.get("name") or "light"
        try:
            messages.append(control_device(name, True, None))
        except Exception as e:
            print(f"[SmartHome] run_coding_ambience failed for {name}: {e}")
    return " ".join(messages) if messages else "Smart devices did not respond."


def execute_smart_command(text: str) -> str:
    text_lower = text.lower()
    
    state = False
    if " on" in text_lower or "start" in text_lower:
        state = True
        
    device = "lights" # Fallback guess
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
            elif "plug" in text_lower or "socket" in text_lower: device = "plug"
    else:
        if "fan" in text_lower: device = "fan"
        elif "tv" in text_lower: device = "TV"
        elif "ac " in text_lower or "air conditioner" in text_lower: device = "AC"
        elif "bulb" in text_lower or "light" in text_lower: device = "light"
        elif "plug" in text_lower or "socket" in text_lower: device = "plug"

    color = None
    colors = ["red", "blue", "green", "yellow", "purple", "white", "warm", "cool"]
    for c in colors:
        if c in text_lower:
            color = c
            break
            
    return control_device(device, state, color)
