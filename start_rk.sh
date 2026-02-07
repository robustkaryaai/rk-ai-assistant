#!/bin/bash
# Startup script for RK AI Assistant
# This script should be located in ~/Documents/rk-ai-assistant/start_rk.sh

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "[startup] Starting at $SCRIPT_DIR"

# Navigate to project directory
cd "$SCRIPT_DIR" || exit 1

# ============================================================
# PRE-FLIGHT BLUETOOTH & AUDIO CHECK
# Wait for hci1 and verify bluez-alsa is ready
# ============================================================
echo "[startup] Running pre-flight Bluetooth check..."

# Restart bluetooth service first
echo "[startup] Restarting bluetooth service..."
sudo systemctl restart bluetooth 2>/dev/null || true
sleep 5

# 1. Wait for hci1 to be initialized (can take up to 60 seconds after boot)
echo "[startup] Waiting for Bluetooth adapter hci1 to initialize..."
MAX_WAIT=60
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    if sudo hciconfig hci1 2>/dev/null | grep -q "UP RUNNING"; then
        echo "[startup] ✓ hci1 is UP and RUNNING"
        break
    fi
    
    # If hci1 exists but is DOWN, try to bring it up
    if sudo hciconfig hci1 2>/dev/null | grep -q "DOWN"; then
        echo "[startup] hci1 is DOWN, attempting to bring it up..."
        sudo hciconfig hci1 up 2>/dev/null || echo "[startup] Failed to bring up hci1"
        sleep 1
    fi
    
    if [ $ELAPSED -eq 0 ]; then
        echo "[startup] Waiting for hci1..."
    fi
    
    sleep 2
    ELAPSED=$((ELAPSED + 2))
    
    if [ $((ELAPSED % 10)) -eq 0 ]; then
        echo "[startup]   Still waiting... (${ELAPSED}s/${MAX_WAIT}s)"
    fi
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    echo "[startup] ⚠️  WARNING: hci1 did not initialize within ${MAX_WAIT}s"
    echo "[startup] Available HCI interfaces:"
    sudo hciconfig || true
    echo "[startup] System will reboot in 10 seconds to recover..."
    sleep 10
    sudo reboot
    exit 1
else
    echo "[startup] hci1 ready after ${ELAPSED}s"
fi

# 2. Ensure PulseAudio is running
if ! pulseaudio --check; then
    echo "[startup] Starting PulseAudio..."
    pulseaudio --start --exit-idle-time=-1 || echo "[startup] Warning: Failed to start PulseAudio"
    sleep 2
fi

# 3. Connect to speaker (One-time "Fire and Forget")
echo "[startup] Resolving Bluetooth MAC..."
# Use python to get the MAC (handles .env and defaults correctly)
SPEAKER_MAC=$(python3 -c "from rk_assistant.config import BLUETOOTH_SPEAKER_MAC; print(BLUETOOTH_SPEAKER_MAC)" 2>/dev/null)

if [ ! -z "$SPEAKER_MAC" ]; then
    echo "[startup] Target Speaker: $SPEAKER_MAC"
    
    # Reload PulseAudio Bluetooth linkage to clear "UUID already registered"
    pactl unload-module module-bluez5-discover 2>/dev/null || true
    pactl load-module module-bluez5-discover 2>/dev/null || true
    
    # Trust but verify connection
    echo "[startup] Connecting..."
    bluetoothctl connect "$SPEAKER_MAC" || true
    
    # Check
    if bluetoothctl info "$SPEAKER_MAC" | grep -q "Connected: yes"; then
         echo "[startup] ✓ Connected successfully"
         # Ensure default sink is set
         pactl set-default-sink bluez_sink.$(echo "$SPEAKER_MAC" | tr ':' '_').a2dp_sink 2>/dev/null || true
    fi
    
    # Give it a moment to stabilize audio path
    sleep 5
else
    echo "[startup] Warning: Could not resolve BLUETOOTH_SPEAKER_MAC"
fi

echo "[startup] ✓ Bluetooth ready (OS Managed)"
echo "[startup] ✓ Pre-flight check complete"

# Activate virtual environment
# Assuming rk-ai is in the parent directory (Documents)
if [ -f "../rk-ai/bin/activate" ]; then
    source ../rk-ai/bin/activate
elif [ -f "../../rk-ai/bin/activate" ]; then
    source ../../rk-ai/bin/activate
else
    echo "[startup] Error: Virtual environment 'rk-ai' not found."
    # Try system python if venv fails, or just exit
fi

# Update from git
echo "[startup] Checking for updates..."
git pull origin main

echo "[startup] Starting RK AI Assistant..."
# Capture stderr too
python3 -m rk_assistant.main
