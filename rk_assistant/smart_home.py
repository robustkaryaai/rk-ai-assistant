"""
Smart Home Controller for RK AI Assistant.
Focused on Xiaomi / Mi Home LAN discovery and local MiIO control.
RK tries to discover supported devices and tokens automatically on the same Wi-Fi.
"""

import os
import re
import subprocess
import sys
import requests
import threading
import time
import json
import asyncio
from typing import Dict, List
from .settings_sync import get_smart_devices, get_xiaomi_oauth_config, device_settings
from .config import RK_WEBHOOK_SECRET, GEMINI_API_KEY, GEMINI_API_KEY_BACKUP

BACKEND_BASE_URL = os.getenv('BACKEND_BASE_URL', 'https://rk-ai-backend.onrender.com')
XIAOMI_OAUTH_API_BASE_URL = os.getenv('XIAOMI_OAUTH_API_BASE_URL', BACKEND_BASE_URL)
DEVICE_SLUG = os.getenv('DEVICE_SLUG', '').strip()

# Only one discovery at a time — parallel scans break asyncio.run() and duplicate TTS/work.
_discover_lock = threading.Lock()

# Short TTL cache — avoids repeated list copies during one voice burst; invalidated on discovery.
_DEVICES_CACHE_TTL_SEC = 3.0
_devices_cache_ts = 0.0
_devices_cache_list = None

# Voice color names → RGB (Yeelight LAN)
def _webhook_request_headers() -> dict:
    h = {}
    if RK_WEBHOOK_SECRET:
        h["X-RK-Webhook-Secret"] = RK_WEBHOOK_SECRET
    return h


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


def _discover_miio_entries():
    """Find Xiaomi MiIO devices on LAN and keep only entries with usable local tokens."""
    entries = []

    try:
        from miio.discovery import Discovery

        if hasattr(Discovery, "discover_mdns"):
            md = Discovery.discover_mdns(timeout=6)
            if md:
                for item in md:
                    ip = getattr(item, "ip", None)
                    if ip is None and hasattr(item, "dinfo") and callable(getattr(item, "dinfo", None)):
                        try:
                            info = item.dinfo()
                            ip = getattr(info, "ip", None) if info else None
                        except Exception:
                            ip = None
                    if not ip:
                        continue
                    tok = getattr(item, "token", None)
                    rec = {
                        "id": f"miio_{ip}",
                        "name": f"Xiaomi {ip}",
                        "provider": "xiaomi",
                        "brand": "Xiaomi",
                        "type": "miio",
                        "room": "",
                        "cloud": False,
                        "source": "local",
                        "control_via": "hub",
                        "ip": ip,
                        "on_url": f"http://{ip}/on",
                        "off_url": f"http://{ip}/off",
                    }
                    if tok and len(str(tok).replace(" ", "")) == 32:
                        rec["token"] = str(tok).replace(" ", "").lower()
                    entries.append(rec)
    except ImportError:
        pass
    except Exception as e:
        print(f"[SmartHome] MiIO mDNS: {e}")

    def _run_cli_discover():
        import shutil

        for cmd in (
            ["miiocli", "discover"],
            [sys.executable, "-m", "miio.cli", "discover"],
        ):
            if cmd[0] != sys.executable and not shutil.which(cmd[0]):
                continue
            try:
                r = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=24,
                    check=False,
                )
                return (r.stdout or "") + "\n" + (r.stderr or "")
            except Exception:
                continue
        return ""

    text = _run_cli_discover()
    if text.strip():
        seen_ip = {e["ip"] for e in entries}
        for m in re.finditer(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", text):
            ip = m.group(1)
            if ip.startswith("127.") or ip in seen_ip:
                continue
            seen_ip.add(ip)
            tok = None
            tm = re.search(
                rf"{re.escape(ip)}[^\n]{{0,160}}(?i)token[:=\s]+([0-9a-f]{{32}})",
                text,
            )
            if tm:
                tok = tm.group(1).lower()
            rec = {
                "id": f"miio_{ip}",
                "name": f"Xiaomi {ip}",
                "provider": "xiaomi",
                "brand": "Xiaomi",
                "type": "miio",
                "room": "",
                "cloud": False,
                "source": "local",
                "control_via": "hub",
                "ip": ip,
                "on_url": f"http://{ip}/on",
                "off_url": f"http://{ip}/off",
            }
            if tok:
                rec["token"] = tok
            entries.append(rec)

    connected_entries = []
    skipped = 0
    for entry in entries:
        token = str(entry.get("token") or "").replace(" ", "").strip().lower()
        if len(token) == 32:
            entry["token"] = token
            connected_entries.append(entry)
        else:
            skipped += 1

    if not connected_entries:
        print(
            "[SmartHome] No Xiaomi MiIO devices discovered with usable local tokens. "
            "Ensure the device is on the same Wi-Fi as RK and python-miio is installed."
        )
    else:
        print(
            f"[SmartHome] Xiaomi discovery: {len(connected_entries)} ready device(s)"
            + (f" | skipped {skipped} without token" if skipped else "")
        )
    return connected_entries


def _xiaomi_merge_key(device: dict) -> str:
    did = str(device.get("did") or "").strip()
    ip = str(device.get("ip") or "").strip()
    dev_id = str(device.get("id") or "").strip()
    if did:
        return f"did:{did}"
    if ip:
        return f"ip:{ip}"
    return f"id:{dev_id}"


def _merge_xiaomi_devices(*groups: List[dict]) -> List[dict]:
    merged: Dict[str, dict] = {}
    for group in groups:
        for item in group or []:
            if not isinstance(item, dict):
                continue
            key = _xiaomi_merge_key(item)
            previous = merged.get(key, {})
            combined = {**previous, **item}

            # Preserve user-set room/aliases when already known.
            if previous.get("room"):
                combined["room"] = previous["room"]
            if previous.get("aliases"):
                combined["aliases"] = previous["aliases"]

            prev_name = str(previous.get("name") or "").strip()
            next_name = str(item.get("name") or "").strip()
            if prev_name and not prev_name.lower().startswith("xiaomi "):
                combined["name"] = prev_name
            elif next_name:
                combined["name"] = next_name

            merged[key] = combined
    return list(merged.values())


def _fetch_backend_xiaomi_devices() -> List[dict]:
    cfg = get_xiaomi_oauth_config()
    user_id = str(cfg.get("user_id") or cfg.get("userId") or "").strip()
    if not user_id:
        return []

    try:
        response = requests.get(
            f"{XIAOMI_OAUTH_API_BASE_URL.rstrip('/')}/xiaomi/devices/{user_id}",
            timeout=10,
        )
        payload = response.json() if response.ok else {}
        if not response.ok:
            print(f"[SmartHome] Xiaomi OAuth device fetch failed | status={response.status_code} detail={payload}")
            return []

        devices = payload.get("devices") if isinstance(payload, dict) else []
        entries = [item for item in devices if isinstance(item, dict)]
        print(f"[SmartHome] Xiaomi OAuth device fetch OK | user_id={user_id} devices={len(entries)}")
        return entries
    except Exception as exc:
        print(f"[SmartHome] Xiaomi OAuth device fetch error | err={exc}")
        return []


def _lan_broadcast_addresses():
    """/24 broadcast IPs for each non-loopback IPv4 on this host (helps Kasa UDP discovery)."""
    try:
        out = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=2, check=False
        )
        seen = []
        for ip in (out.stdout or "").split():
            ip = ip.strip()
            if not ip or ip.startswith("127."):
                continue
            parts = ip.split(".")
            if len(parts) == 4:
                b = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
                if b not in seen:
                    seen.append(b)
        return seen
    except Exception:
        return []


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
    if "token" in msg or "auth" in msg or ("invalid" in msg and "token" in msg):
        return f"{device_label} auth failed — check Mi token or pairing."
    if "name or service not known" in msg or "gaierror" in msg:
        return f"{device_label} DNS/hostname issue — use IP for local control."
    return f"{device_label}: {str(err)[:160]}"


def _backend_proxy_control(device_id: str, action: str, payload: dict = None) -> str:
    if not DEVICE_SLUG:
        return "Smart-home cloud control needs DEVICE_SLUG on the RK hub."

    try:
        res = requests.post(
            f"{BACKEND_BASE_URL}/device/{DEVICE_SLUG}/smart-home/control",
            json={
                "id": device_id,
                "action": action,
                "payload": payload or {},
            },
            timeout=10,
        )
        data = res.json() if res.content else {}
        if not res.ok:
            return data.get("error") or f"Cloud control failed ({res.status_code})."
        return ""
    except requests.exceptions.Timeout as e:
        return _format_control_error(e, "Cloud device")
    except requests.exceptions.RequestException as e:
        return _format_control_error(e, "Cloud device")
    except Exception as e:
        return str(e)


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
        candidates = [str(d.get("name", "")).lower().strip()]
        room = str(d.get("room", "")).lower().strip()
        if room:
            candidates.append(room)
            nm = str(d.get("name", "")).lower().strip()
            if nm:
                candidates.append(f"{room} {nm}")
        brand = str(d.get("brand", "")).lower().strip()
        if brand:
            candidates.append(brand)
        for alias in (d.get("aliases") or []):
            alias = str(alias).lower().strip()
            if alias:
                candidates.append(alias)

        local_best = -1
        local_name = ""
        for name in candidates:
            if not name:
                continue
            d_tokens = set(re.findall(r"[a-z0-9]+", name))
            overlap = len(q_tokens & d_tokens)
            if len(name) >= 3 and name in q:
                overlap += 4
            if len(q) >= 3 and q in name:
                overlap += 2
            score = overlap * 1000 + len(name)
            if overlap >= 1 and score > local_best:
                local_best = score
                local_name = name

        if local_best > best_score:
            best_score = local_best
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
    # Serialize scans — parallel asyncio.run + UDP discover corrupts results.
    with _discover_lock:
        return _discover_and_sync_devices_impl(slug)


def _discover_and_sync_devices_impl(slug: str) -> dict:
    print("[SmartHome] Starting Xiaomi discovery (LAN + backend-synced devices)...")
    local_devices = []
    oauth_devices = []

    # Xiaomi MiIO (LAN)
    try:
        for d in _discover_miio_entries():
            if d["ip"] not in {x.get("ip") for x in local_devices}:
                local_devices.append(d)
    except Exception as e:
        print(f"[SmartHome] MiIO discovery error: {e}")

    if not local_devices:
        print(
            "[SmartHome] No Xiaomi devices auto-connected. "
            "No usable LAN tokens were found from local discovery."
        )

    # Pull merged OAuth + QR devices from the backend service when a Xiaomi user identity is linked.
    oauth_devices = _fetch_backend_xiaomi_devices()

    # Preserve backend-synced Xiaomi devices and merge in any fresh LAN discoveries.
    existing = get_smart_devices()
    existing_xiaomi = [
        d for d in existing
        if str(d.get("provider") or d.get("type") or "").lower() in ("xiaomi", "miio", "mihome")
    ]
    final_devices = _merge_xiaomi_devices(existing_xiaomi, oauth_devices, local_devices)

    print(
        "[SmartHome] Xiaomi merge complete | "
        f"existing={len(existing_xiaomi)} oauth={len(oauth_devices)} local={len(local_devices)} total={len(final_devices)}"
    )
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
            "count": len(local_devices) + len(oauth_devices),
            "local_count": len(local_devices),
            "oauth_count": len(oauth_devices),
            "devices_found": list(oauth_devices) + list(local_devices),
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
        if matched_device.get("control_via") == "backend_proxy" or matched_device.get("provider") == "tuya":
            err = _backend_proxy_control(
                str(matched_device.get("id") or matched_device.get("provider_device_id") or ""),
                "on" if state else "off",
                {"color": color} if color else {},
            )
            if err:
                return err
            action_str = "Turned on" if state else "Turned off"
            return f"{action_str} the {matched_device.get('name')}."

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

            res = requests.get(url, timeout=4, headers=_webhook_request_headers())
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
            if matched.get("control_via") == "backend_proxy" or matched.get("provider") == "tuya":
                current = None
                raw_status = matched.get("raw_status") or []
                if isinstance(raw_status, list):
                    switch_code = ((matched.get("control_codes") or {}).get("switch")) or ""
                    for row in raw_status:
                        if row.get("code") == switch_code or "switch" in str(row.get("code", "")):
                            if isinstance(row.get("value"), bool):
                                current = row.get("value")
                                break
                err = _backend_proxy_control(device_id, "off" if current else "on")
                if err:
                    return err
                return f"Toggled {name}."

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
                requests.get(tu, timeout=4, headers=_webhook_request_headers())
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
    t = (text or "").lower()
    if any(
        x in t
        for x in (
            "turn on",
            "turn off",
            "switch on",
            "switch off",
            "lights out",
            "power on",
            "power off",
            "all lights",
            "every light",
            "everything off",
            "everything on",
            "shut off",
            "flip on",
            "flip off",
        )
    ):
        if any(
            w in t
            for w in (
                "light",
                "bulb",
                "lamp",
                "fan",
                "plug",
                "socket",
                "switch",
                "strip",
                "tv",
                "ac ",
                "air con",
                "outlet",
                "device",
                "room",
                "all ",
                "every ",
            )
        ):
            return True
        for d in _get_smart_devices_cached():
            name = str(d.get("name", "")).lower().strip()
            if len(name) >= 3 and name in t:
                return True
    if re.search(r"\b(dim|brighten)\s+(the\s+)?(lights?|room)\b", t):
        return True
    return False
    
_VOICE_COLORS = ("red", "blue", "green", "yellow", "purple", "white", "warm", "cool")


def _extract_color_from_text(text: str):
    tl = text.lower()
    for c in _VOICE_COLORS:
        if re.search(rf"\b{re.escape(c)}\b", tl):
            return c
    return None


def _parse_smart_home_rules(text: str) -> tuple:
    """
    Alexa-style rule parse → (state: bool, device_query: str, color: str|None).
    device_query '__all__' = whole home; '' = unknown target (try LLM / hub names).
    """
    raw = text or ""
    t = raw.lower().strip()
    t = re.sub(r"[^\w\s\-\']", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    color = _extract_color_from_text(t)
    t_dev = t
    for c in _VOICE_COLORS:
        t_dev = re.sub(rf"\b{re.escape(c)}\b", " ", t_dev)
    t_dev = re.sub(r"\s+", " ", t_dev).strip()

    if "lights out" in t or re.search(
        r"\b(all|every|everything)\s+(the\s+)?(lights?|devices?|plugs?|bulbs?)\s+off\b", t_dev
    ) or t_dev in ("all off", "everything off", "switch off all", "turn off all"):
        return False, "__all__", color
    if re.search(
        r"\b(all|every|everything)\s+(the\s+)?(lights?|devices?|plugs?|bulbs?)\s+on\b", t_dev
    ) or t_dev in ("all on", "everything on"):
        return True, "__all__", color

    m = re.search(r"\b(?:turn|switch|flip)\s+(on|off)\s+(?:the\s+)?(.+)$", t_dev)
    if m:
        return m.group(1) == "on", m.group(2).strip(), color

    m = re.search(r"\b(?:turn|switch|flip)\s+(?:the\s+)?(.+?)\s+(on|off)\s*$", t_dev)
    if m:
        phrase = m.group(1).strip()
        if phrase not in ("it", "that", "this", "them", "there", "here"):
            return m.group(2) == "on", phrase, color

    m = re.search(r"\b(?:power|switch)\s+(on|off)\s+(?:the\s+)?(.+)$", t_dev)
    if m:
        return m.group(1) == "on", m.group(2).strip(), color

    on_hit = bool(re.search(r"\b(turn on|switch on|power on|enable|activate)\b", t_dev))
    off_hit = bool(
        re.search(r"\b(turn off|switch off|power off|disable|deactivate|shut off)\b", t_dev)
    )
    if on_hit or off_hit:
        state = on_hit and not off_hit
        rest = t_dev
        for pat in (
            r"\bturn\s+on\s+(?:the\s+)?",
            r"\bturn\s+off\s+(?:the\s+)?",
            r"\bswitch\s+on\s+(?:the\s+)?",
            r"\bswitch\s+off\s+(?:the\s+)?",
            r"\bpower\s+on\s+(?:the\s+)?",
            r"\bpower\s+off\s+(?:the\s+)?",
            r"\benable\s+(?:the\s+)?",
            r"\bdisable\s+(?:the\s+)?",
            r"\bactivate\s+(?:the\s+)?",
            r"\bdeactivate\s+(?:the\s+)?",
            r"\bshut\s+off\s+(?:the\s+)?",
        ):
            rest = re.sub(pat, "", rest, count=1)
        rest = re.sub(r"\s+", " ", rest).strip()
        if rest and rest not in ("it", "that", "this", "please"):
            return state, rest, color

    # Hub name appears in utterance (e.g. "bedroom lamp is too bright" → off is harder; keep simple)
    if on_hit or off_hit:
        devs = _get_smart_devices_cached()
        best = ""
        best_name = ""
        for d in devs:
            name = str(d.get("name", "")).strip()
            if len(name) < 2:
                continue
            nl = name.lower()
            if nl in t_dev and len(name) > len(best_name):
                best_name = name
                best = name
        if best:
            return (on_hit and not off_hit), best, color

    # Keyword-only device guess (legacy)
    if "fan" in t_dev:
        return (on_hit or not off_hit), "fan", color
    if "plug" in t_dev or "socket" in t_dev or "outlet" in t_dev:
        return (on_hit or not off_hit), "plug", color
    if "tv" in t_dev:
        return (on_hit or not off_hit), "TV", color
    if "ac" in t_dev or "air conditioner" in t_dev or "aircon" in t_dev:
        return (on_hit or not off_hit), "AC", color
    if "bulb" in t_dev or "lamp" in t_dev or "light" in t_dev:
        return (on_hit or not off_hit), "light", color

    return (on_hit and not off_hit) if (on_hit ^ off_hit) else True, "", color


def _control_all_devices(state: bool, color: str = None) -> str:
    devs = _get_smart_devices_cached()
    if not devs:
        return "No devices in your hub yet. Add them in the RK app under Smart Hub."
    parts = []
    for d in devs:
        did = d.get("id")
        try:
            if did:
                parts.append(control_device_by_id(str(did), "on" if state else "off"))
            else:
                nm = d.get("name") or "device"
                parts.append(control_device(nm, state, color))
        except Exception as e:
            parts.append(str(e))
    # Keep voice reply short
    ok = sum(1 for p in parts if "off" in p.lower() or "on" in p.lower() or "toggled" in p.lower())
    return f"Ran whole-home {'on' if state else 'off'} for {ok} of {len(devs)} devices."


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
    state, query, color = _parse_smart_home_rules(text)

    if query == "__all__":
        return _control_all_devices(state, color)

    if not query.strip():
        try:
            from .gemini_client import parse_smart_home_command

            gh = parse_smart_home_command(text, GEMINI_API_KEY, GEMINI_API_KEY_BACKUP)
            if gh:
                state, gq, gc = gh
                if gc:
                    color = gc
                if gq:
                    if str(gq).upper() == "ALL" or str(gq).strip().lower() in (
                        "all devices",
                        "everything",
                        "whole house",
                    ):
                        return _control_all_devices(state, color)
                    query = str(gq).strip()
        except Exception as e:
            print(f"[SmartHome] LLM parse skipped: {e}")

    if not query.strip():
        query = "light"

    return control_device(query, state, color)
