"""
Smart Home Controller for RK AI Assistant.
Reads the user's configured Wi-Fi appliances from Appwrite and sends local HTTP Webhooks.
Includes discovery for TP-Link (Kasa/Tapo) and Yeelight LAN.
Xiaomi / Mi Home Wi-Fi bulbs: add manually in the RK app (IP + 32-char token) with type "miio".
Requires: pip install python-miio (same LAN as the Pi; token from Mi Cloud / extractor tools).
"""

import os
import re
import requests
import time
import json
import asyncio
from .settings_sync import get_smart_devices, device_settings

BACKEND_BASE_URL = os.getenv('BACKEND_BASE_URL', 'https://rk-ai-backend.onrender.com')

# Short TTL cache — avoids repeated list copies during one voice burst; invalidated on discovery.
_DEVICES_CACHE_TTL_SEC = 3.0
_devices_cache_ts = 0.0
_devices_cache_list = None

# Voice color names → RGB (Yeelight LAN)
_YEELIGHT_COLOR_RGB = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "purple": (128, 0, 128),
    "white": (255, 255, 255),
    "warm": (255, 200, 120),
    "cool": (220, 235, 255),
}


def _invalidate_devices_cache() -> None:
    global _devices_cache_ts, _devices_cache_list
    _devices_cache_list = None
    _devices_cache_ts = 0.0


def _get_smart_devices_cached():
    """Shallow snapshot of hub list (refreshed from RAM or TTL)."""
    global _devices_cache_ts, _devices_cache_list
    now = time.time()
    if _devices_cache_list is not None and (now - _devices_cache_ts) < _DEVICES_CACHE_TTL_SEC:
        return _devices_cache_list
    raw = get_smart_devices()
    if not raw:
        _devices_cache_list = []
    else:
        _devices_cache_list = list(raw)
    _devices_cache_ts = now
    return _devices_cache_list


def _format_control_error(err: Exception, device_label: str) -> str:
    msg = str(err).lower()
    if "timeout" in msg or "timed out" in msg:
        return f"{device_label} timed out — check LAN, IP, or that the device is powered."
    if "connection" in msg or "refused" in msg or "unreachable" in msg or "no route" in msg:
        return f"{device_label} unreachable — offline, wrong IP, or wrong VLAN."
    if "token" in msg or "auth" in msg or "invalid" in msg and "token" in msg:
        return f"{device_label} auth failed — check Mi token or pairing."
    if "name or service not known" in msg or "gaierror" in msg:
        return f"{device_label} DNS/hostname issue — use IP for local control."
    return f"{device_label}: {str(err)[:160]}"


def _match_device_by_voice_query(query: str, devices: list):
    """
    Prefer stable id match, then token overlap + longest name — avoids 'light' matching every device.
    """
    if not devices:
        return None
    q = (query or "").lower().strip()
    if not q:
        return None

    # 1) Exact id (e.g. user or automation passes kasa_abc / yeelight_192...)
    for d in devices:
        did = d.get("id")
        if did and str(did).lower() == q:
            return d

    # 2) Single device — unambiguous
    if len(devices) == 1:
        return devices[0]

    stop = frozenset(
        "the a an on off turn switch my to please all lights light lights "
        "it that this".split()
    )
    q_tokens = set(re.findall(r"[a-z0-9]+", q)) - stop
    if not q_tokens:
        q_tokens = set(re.findall(r"[a-z0-9]+", q))

    best = None
    best_score = -1
    for d in devices:
        name = str(d.get("name", "")).lower().strip()
        if not name:
            continue
        d_tokens = set(re.findall(r"[a-z0-9]+", name))
        overlap = len(q_tokens & d_tokens)
        if len(name) >= 3 and name in q:
            overlap += 4
        if len(q) >= 3 and q in name:
            overlap += 2
        # Prefer longer names on tie (more specific, e.g. "bedroom light" vs "light")
        tie_break = len(name)
        score = overlap * 1000 + tie_break
        if overlap >= 1 and score > best_score:
            best_score = score
            best = d

    if best is not None and best_score >= 1000:  # token overlap and/or substring boost
        return best

    # 3) Last resort: only if query is a single generic word and exactly one bulb-like name matches
    generic = frozenset(("light", "lights", "bulb", "lamp", "fan", "plug"))
    if q in generic or (len(q_tokens) > 0 and q_tokens.issubset(generic)):
        candidates = [d for d in devices if any(
            x in str(d.get("name", "")).lower() for x in ("light", "bulb", "lamp")
        )]
        if len(candidates) == 1:
            return candidates[0]

    return None


def _yeelight_apply_color(bulb, color_name) -> None:
    if not color_name:
        return
    c = str(color_name).lower().strip()
    if c not in _YEELIGHT_COLOR_RGB:
        return
    r, g, b = _YEELIGHT_COLOR_RGB[c]
    rgb_int = (r << 16) | (g << 8) | b
    try:
        bulb.set_rgb(rgb_int)
    except Exception:
        try:
            bulb.set_rgb(r, g, b)
        except Exception as ex:
            print(f"[SmartHome] yeelight set_rgb failed: {ex}")


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
        requests.post(
            f"{BACKEND_BASE_URL}/device/{slug}/update-status",
            json={"smart_devices": final_devices},
            timeout=10,
        )
        try:
            device_settings["smart_devices"] = final_devices
        except Exception as ex:
            print(f"[SmartHome] local device_settings update: {ex}")
        _invalidate_devices_cache()
        return {
            "success": True,
            "count": len(devices),
            "devices_found": list(devices),
            "total_registered": len(final_devices),
            "devices": final_devices,
        }
    except Exception as e:
        print(f"[SmartHome] Sync failed: {e}")
        return {"success": False, "error": str(e)}


def control_device(device_name: str, state: bool, color: str = None) -> str:
    smart_devices = _get_smart_devices_cached()
    print(f"[SmartHome] Action: {'Turn ON' if state else 'Turn OFF'} | Spoken: {device_name} | Color: {color or 'default'}")

    matched_device = _match_device_by_voice_query(device_name, smart_devices)
    if not matched_device:
        return f"I couldn't find a device matching «{device_name}» in your hub list. Say the name you saved or add more words (e.g. bedroom light)."

    return _apply_power(matched_device, state, color)


def _apply_power(matched_device: dict, state: bool, color: str = None) -> str:
    """Apply on/off to a matched device record (kasa / yeelight / miio / webhook)."""
    dev_type = matched_device.get("type", "webhook")
    ip = matched_device.get("ip")

    try:
        if dev_type == "kasa" and ip:
            from kasa import SmartDevice

            async def kasa_power():
                dev = SmartDevice(ip)
                await dev.update()
                if state:
                    await dev.turn_on()
                else:
                    await dev.turn_off()

            asyncio.run(kasa_power())
            action_str = "Turned on" if state else "Turned off"
            return f"{action_str} the {matched_device.get('name')}."

        elif dev_type == "yeelight" and ip:
            from yeelight import Bulb

            bulb = Bulb(ip)
            if state:
                bulb.turn_on()
                _yeelight_apply_color(bulb, color)
            else:
                bulb.turn_off()
            action_str = "Turned on" if state else "Turned off"
            suffix = f" ({color})" if state and color else ""
            return f"{action_str} the {matched_device.get('name')}{suffix}."

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

        else:
            url = matched_device.get("on_url") if state else matched_device.get("off_url")
            if not url:
                return f"The {matched_device.get('name')} doesn't have a configured URL for this action."

            res = requests.get(url, timeout=4)
            print(f"[SmartHome] Webhook executed: {res.status_code}")
            action_str = "Turned on" if state else "Turned off"
            suffix = f" and set color to {color}" if color else ""
            return f"{action_str} the {matched_device.get('name')}{suffix}."

    except requests.exceptions.Timeout as e:
        print(f"[SmartHome] timeout: {e}")
        return _format_control_error(e, matched_device.get("name", "Device"))
    except requests.exceptions.RequestException as e:
        print(f"[SmartHome] request error: {e}")
        return _format_control_error(e, matched_device.get("name", "Device"))
    except Exception as e:
        print(f"[SmartHome] Request/Native Protocol failed: {e}")
        return _format_control_error(e, matched_device.get("name", "Device"))


def control_device_by_id(device_id: str, action: str = "toggle") -> str:
    """
    Control a device by stable id (from discovery / smart_devices list).
    action: toggle | on | off
    """
    action = (action or "toggle").lower().strip()
    if action not in ("toggle", "on", "off"):
        return f"Unknown action: {action}"

    smart_devices = _get_smart_devices_cached()
    matched = next((d for d in smart_devices if d.get("id") == device_id), None)
    if not matched:
        return f"No device with id {device_id} in your hub list."

    dev_type = matched.get("type", "webhook")
    ip = matched.get("ip")
    name = matched.get("name") or "device"

    if action == "toggle":
        try:
            if dev_type == "kasa" and ip:
                from kasa import SmartDevice

                async def kasa_toggle():
                    dev = SmartDevice(ip)
                    await dev.update()
                    if dev.is_on:
                        await dev.turn_off()
                    else:
                        await dev.turn_on()

                asyncio.run(kasa_toggle())
                return f"Toggled {name}."

            if dev_type == "yeelight" and ip:
                from yeelight import Bulb

                bulb = Bulb(ip)
                try:
                    bulb.toggle()
                except Exception:
                    try:
                        props = bulb.get_properties()
                        if isinstance(props, dict) and props.get("power") == "on":
                            bulb.turn_off()
                        else:
                            bulb.turn_on()
                    except Exception:
                        bulb.turn_on()
                return f"Toggled {name}."

            if dev_type in ("miio", "xiaomi", "mihome") and ip:
                token = matched.get("token") or matched.get("mi_token")
                if not token:
                    return f"Add a Mi token for {name} on the hub."
                try:
                    from miio import Device

                    tok = token.replace(" ", "").strip().lower()
                    mdl = matched.get("miio_model")
                    dev = Device(ip, tok, model=mdl) if mdl else Device(ip, tok)
                    try:
                        dev.send("toggle", [])
                    except Exception:
                        _control_miio(ip, tok, True, matched.get("miio_model"))
                    return f"Toggled {name}."
                except ImportError:
                    return "python-miio is not installed on the hub."
                except Exception as e:
                    print(f"[SmartHome] miio toggle: {e}")
                    return _apply_power(matched, True, None)

            tu = matched.get("toggle_url")
            if tu:
                requests.get(tu, timeout=4)
                return f"Toggled {name}."
            return (
                f"Toggle needs a native device (Kasa/Yeelight/Mi) or a toggle_url for webhooks. "
                f"Configure {name} or use Turn on/off from voice."
            )

        except Exception as e:
            print(f"[SmartHome] toggle failed: {e}")
            return f"I couldn't toggle {name}: {e}"

    return _apply_power(matched, action == "on", None)
    
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
    devices = _get_smart_devices_cached()
    if not devices:
        return "No smart devices are paired yet. Pair lights in the RK app under Smart Hub, then try again."

    messages = []
    for d in devices:
        did = d.get("id")
        try:
            if did:
                messages.append(control_device_by_id(str(did), "on"))
            else:
                messages.append(control_device(d.get("name") or "light", True, None))
        except Exception as e:
            print(f"[SmartHome] run_coding_ambience failed for {d.get('name')}: {e}")
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
