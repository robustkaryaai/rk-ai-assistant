"""
Appwrite Settings Sync (Depreciated) -> Render Backend Sync
Polls the Render backend for device settings (TTS, wake words, etc.)
"""
import os
import time
import requests
import json
from threading import Thread

# Try to get the BACKEND URL from config, otherwise fallback
try:
    from .config import BACKEND_BASE_URL
except ImportError:
    BACKEND_BASE_URL = os.getenv('BACKEND_BASE_URL', 'https://rk-ai-backend.onrender.com')

DEVICE_SLUG = os.getenv('DEVICE_SLUG', '')

# Global state
device_settings = {
    'is_muted': False,
    'memory_enabled': True,
    'assistant_name': 'RK',
    'greeting_phrase': 'Radhe Radhe',
    'wake_words': ['rk', 'arc', 'hey rk', 'okay rk'],
    'night_protocol_enabled': True,
    'smart_devices': [],
    'tts_config': {
        'engine': 'gtts',
        'voice': 'co.in',
        'gender': 'female',
        'language': 'hi',
    },
}

def poll_device_settings(slug):
    """Poll Render every 30 seconds for device settings"""
    if not slug:
        print(f"[Settings Sync] Missing device slug, skipping sync")
        return
    
    print(f"[Settings Sync] Starting sync for device: {slug}")
    
    while True:
        try:
            refresh_device_settings_now(slug)
        except Exception as e:
            print(f"[Settings Sync] Error polling backend: {e}")
        
        # Poll every 30 seconds
        time.sleep(30)

def start_settings_sync(slug):
    """Start background thread to poll device settings"""
    thread = Thread(target=poll_device_settings, args=(slug,), daemon=True)
    thread.start()
    print(f"[Settings Sync] Background sync started for {slug}")


def refresh_device_settings_now(slug=None):
    """Fetch the latest device settings immediately and apply them to local cache."""
    slug = slug or DEVICE_SLUG
    if not slug:
        return False

    url = f"{BACKEND_BASE_URL}/device/{slug}/settings"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return False

        data = response.json()
        if not data.get('documents') or len(data['documents']) == 0:
            return False

        device = data['documents'][0]


    device_settings['is_muted'] = device.get('isMuted') if device.get('isMuted') is not None else device.get('is_muted', False)
    device_settings['memory_enabled'] = device.get('memoryEnabled') if device.get('memoryEnabled') is not None else device.get('memory_enabled', True)

    if device.get('assistantName'):
        device_settings['assistant_name'] = device['assistantName']

    if device.get('greetingPhrase'):
        device_settings['greeting_phrase'] = device['greetingPhrase']

    if device.get('wakeWords'):
        try:
            wake_words_raw = device['wakeWords']
            wake_words_data = json.loads(wake_words_raw) if isinstance(wake_words_raw, str) else wake_words_raw
            if isinstance(wake_words_data, list):
                device_settings['wake_words'] = [str(w).lower() for w in wake_words_data if str(w).strip()]
            elif isinstance(wake_words_data, dict):
                words = wake_words_data.get('words') or wake_words_data.get('wakeWords') or wake_words_data.get('list') or []
                if isinstance(words, list):
                    device_settings['wake_words'] = [str(w).lower() for w in words if str(w).strip()]

                meta = wake_words_data.get('meta') if isinstance(wake_words_data.get('meta'), dict) else {}
                if 'nightProtocolEnabled' in meta:
                    device_settings['night_protocol_enabled'] = bool(meta['nightProtocolEnabled'])
                if isinstance(meta.get('ttsConfig'), dict):
                    tts_config = dict(device_settings['tts_config'])
                    tts_config.update(meta['ttsConfig'])
                    device_settings['tts_config'] = tts_config
                    print(
                        "[Settings Sync] TTS config synced: "
                        f"engine={tts_config.get('engine')} "
                        f"voice={tts_config.get('voice')} "
                        f"language={tts_config.get('language')} "
                        f"gender={tts_config.get('gender')}"
                    )
        except Exception:
            pass

    if device.get('smart_devices') is not None:
        try:
            devs = device['smart_devices']
            if isinstance(devs, str):
                devs = json.loads(devs)
            if isinstance(devs, list):
                device_settings['smart_devices'] = devs
        except Exception as de:
            print(f"[Settings Sync] smart_devices parse error: {de}")
    return True

def is_device_muted():
    """Check if device is currently muted"""
    return device_settings['is_muted']

def is_memory_enabled():
    """Check if memory saving is enabled"""
    return device_settings['memory_enabled']

def get_assistant_name():
    """Get the current assistant name"""
    return device_settings['assistant_name']

def get_greeting_phrase():
    """Get the current greeting phrase"""
    return device_settings['greeting_phrase']

def get_wake_words():
    """Get the list of active wake words"""
    return device_settings['wake_words']

def is_night_protocol_enabled():
    """Check if auto-quiet Night Protocol is enabled"""
    return device_settings['night_protocol_enabled']

def get_smart_devices():
    """Get the user's configured local smart bulbs/appliances"""
    return device_settings['smart_devices']


def get_tts_config():
    """Get the currently synced TTS configuration."""
    return dict(device_settings['tts_config'])
