"""
Classic Bluetooth (RFCOMM) Server for RK AI Assistant.
Allows Wi-Fi provisioning via standard Bluetooth Serial pairing.
Useful as a robust fallback when BLE GATT is unreliable.
"""

import socket
import json
import threading
import time
import os
import subprocess
from .networking import apply_wifi_credentials, read_slug

# Standard RFCOMM port
RFCOMM_PORT = 1
UUID = "00001101-0000-1000-8000-00805F9B34FB" # Standard Serial Port Profile UUID

def start_classic_bt_server(slug):
    """
    Starts an RFCOMM server that waits for a connection and a JSON payload:
    { "ssid": "...", "password": "..." }
    """
    print(f"[classic-bt] Starting RFCOMM server for RK-AI-{slug}...", flush=True)
    
    try:
        # Create the server socket
        server_sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        server_sock.bind(("", RFCOMM_PORT))
        server_sock.listen(1)
        
        # Make the service discoverable via SDP
        # Note: This requires 'bluez-utils' and 'sdptool' or proper dbus registration.
        # For simplicity on Pi, we assume the startup script made the adapter discoverable.
        try:
            subprocess.run(["sudo", "sdptool", "add", "SP"], capture_output=True)
        except:
            pass

        while True:
            print(f"[classic-bt] Waiting for connection on RFCOMM channel {RFCOMM_PORT}...", flush=True)
            try:
                client_sock, client_info = server_sock.accept()
                print(f"[classic-bt] Accepted connection from {client_info}", flush=True)
                
                # Receive data
                data = client_sock.recv(1024).decode('utf-8')
                if data:
                    print(f"[classic-bt] Received raw data: {data}", flush=True)
                    try:
                        payload = json.loads(data)
                        ssid = payload.get("ssid")
                        password = payload.get("password")
                        
                        if ssid:
                            print(f"[classic-bt] Received credentials for SSID: {ssid}", flush=True)
                            success = apply_wifi_credentials(ssid, password or "")
                            
                            response = {"status": "ok" if success else "error", "message": "Applying Wi-Fi..." if success else "Failed to apply"}
                            client_sock.send(json.dumps(response).encode('utf-8'))
                            
                            if success:
                                print("[classic-bt] Wi-Fi applied successfully. Rebooting in 5s...", flush=True)
                                time.sleep(5)
                                os.system("sudo reboot")
                        else:
                            client_sock.send(json.dumps({"status": "error", "message": "Missing SSID"}).encode('utf-8'))
                    except json.JSONDecodeError:
                        print("[classic-bt] Invalid JSON received", flush=True)
                        client_sock.send(json.dumps({"status": "error", "message": "Invalid JSON"}).encode('utf-8'))
                
                client_sock.close()
            except Exception as e:
                print(f"[classic-bt] Connection error: {e}", flush=True)
                time.sleep(1)
                
    except Exception as e:
        print(f"[classic-bt] Fatal error starting RFCOMM: {e}", flush=True)

if __name__ == "__main__":
    slug_val, _ = read_slug()
    start_classic_bt_server(slug_val or "000000000")
