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

# 1. Wait for hci1 to be initialized (can take up to 60 seconds after boot)
echo "[startup] Waiting for Bluetooth adapter hci1 to initialize..."
MAX_WAIT=60
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    if sudo hciconfig hci1 2>/dev/null | grep -q "UP RUNNING"; then
        echo "[startup] ✓ hci1 is UP and RUNNING"
        break
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

# 2. Basic Bluetooth check  
echo "[startup] ✓ Bluetooth ready (ALSA will auto-route to connected device)"

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
