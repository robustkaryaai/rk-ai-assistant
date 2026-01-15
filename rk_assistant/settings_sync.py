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

# Global state
device_settings = {
    'is_muted': False,
    'memory_enabled': True
}

def poll_device_settings():
    """Poll Appwrite every 30 seconds for device settings"""
    if not all([APPWRITE_ENDPOINT, APPWRITE_PROJECT_ID, APPWRITE_DATABASE_ID, DEVICE_SLUG]):
        print("[Settings Sync] Missing Appwrite config, skipping sync")
        return
    
    while True:
        try:
            # Query Appwrite for device settings
            headers = {
                'X-Appwrite-Project': APPWRITE_PROJECT_ID
            }
            
            url = f"{APPWRITE_ENDPOINT}/databases/{APPWRITE_DATABASE_ID}/collections/{APPWRITE_DEVICES_COLLECTION}/documents"
            params = {
                'queries': [f'equal("slug", {DEVICE_SLUG})']
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('documents') and len(data['documents']) > 0:
                    device = data['documents'][0]
                    
                    # Update global settings
                    device_settings['is_muted'] = device.get('is_muted', False)
                    device_settings['memory_enabled'] = device.get('memory_enabled', True)
                    
                    print(f"[Settings Sync] Updated: muted={device_settings['is_muted']}, memory={device_settings['memory_enabled']}")
            
        except Exception as e:
            print(f"[Settings Sync] Error polling Appwrite: {e}")
        
        # Poll every 30 seconds
        time.sleep(30)

def start_settings_sync():
    """Start background thread to poll device settings"""
    thread = Thread(target=poll_device_settings, daemon=True)
    thread.start()
    print("[Settings Sync] Background sync started")

def is_device_muted():
    """Check if device is currently muted"""
    return device_settings['is_muted']

def is_memory_enabled():
    """Check if memory saving is enabled"""
    return device_settings['memory_enabled']
