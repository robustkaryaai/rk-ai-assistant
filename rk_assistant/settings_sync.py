"""
Appwrite Settings Sync
Polls Appwrite devices collection to sync mute/memory settings from mobile app
"""
import os
import time
import requests
from threading import Thread

APPWRITE_ENDPOINT = os.getenv('APPWRITE_ENDPOINT', 'https://fra.cloud.appwrite.io/v1')
APPWRITE_PROJECT_ID = os.getenv('APPWRITE_PROJECT_ID', '')
APPWRITE_DATABASE_ID = os.getenv('APPWRITE_DATABASE_ID', '')
APPWRITE_DEVICES_COLLECTION = os.getenv('APPWRITE_DEVICES_COLLECTION', 'devices')
DEVICE_SLUG = os.getenv('DEVICE_SLUG', '')

import json

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
    """Poll Appwrite every 30 seconds for device settings"""
    if not all([APPWRITE_ENDPOINT, APPWRITE_PROJECT_ID, APPWRITE_DATABASE_ID, slug]):
        print(f"[Settings Sync] Missing config (slug={slug}), skipping sync")
        return
    
    print(f"[Settings Sync] Starting sync for device: {slug}")
    
    while True:
        try:
            refresh_device_settings_now(slug)
        except Exception as e:
            print(f"[Settings Sync] Error polling Appwrite: {e}")
        
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
    if not all([APPWRITE_ENDPOINT, APPWRITE_PROJECT_ID, APPWRITE_DATABASE_ID, slug]):
        return False

    headers = {
        'X-Appwrite-Project': APPWRITE_PROJECT_ID
    }
    url = f"{APPWRITE_ENDPOINT}/databases/{APPWRITE_DATABASE_ID}/collections/{APPWRITE_DEVICES_COLLECTION}/documents"
    params = {
        'queries': [f'equal("slug", "{slug}")']
    }

    response = requests.get(url, headers=headers, params=params, timeout=10)
    if response.status_code != 200:
        return False

    data = response.json()
    if not data.get('documents'):
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
            words = json.loads(device['wakeWords'])
            if isinstance(words, list):
                device_settings['wake_words'] = [w.lower() for w in words]
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

    if device.get('systemStatus'):
        try:
            sys_status = json.loads(device['systemStatus'])
            if 'nightProtocolEnabled' in sys_status:
                device_settings['night_protocol_enabled'] = bool(sys_status['nightProtocolEnabled'])
            if isinstance(sys_status.get('ttsConfig'), dict):
                tts_config = dict(device_settings['tts_config'])
                tts_config.update(sys_status['ttsConfig'])
                device_settings['tts_config'] = tts_config
            if 'smart_devices' in sys_status and not device_settings['smart_devices']:
                try:
                    devs = sys_status['smart_devices']
                    if isinstance(devs, str):
                        devs = json.loads(devs)
                    device_settings['smart_devices'] = devs
                except Exception as de:
                    print(f"[Settings Sync] Found smart_devices format error: {de}")
        except Exception:
            pass
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
