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
# PRE-FLIGHT AUDIO RECOVERY CHECK
# Check and fix audio issues BEFORE updating code
# ============================================================
echo "[startup] Running pre-flight audio check..."

# Ensure PulseAudio is running first
pulseaudio --start --exit-idle-time=-1 2>/dev/null || echo "[startup] PulseAudio already running"
sleep 2

# Function to check if Bluetooth sink exists
check_bluetooth_sink() {
    pactl list sinks short | grep -i bluez | wc -l
}

# Function to check if any sink is suspended
check_suspended_sinks() {
    pactl list sinks | grep -A 5 "State: SUSPENDED" | wc -l
}

# 1. Check for suspended sinks and unsuspend them
echo "[startup] Checking for suspended audio sinks..."
SUSPENDED_COUNT=$(check_suspended_sinks)
if [ "$SUSPENDED_COUNT" -gt 0 ]; then
    echo "[startup] Found $SUSPENDED_COUNT suspended sink(s), attempting to unsuspend..."
    
    # Get all sink IDs and unsuspend them
    pactl list sinks short | while read sink_id rest; do
        echo "[startup] Unsuspending sink $sink_id..."
        pactl suspend-sink "$sink_id" 0 2>/dev/null
    done
    
    sleep 1
    echo "[startup] Sinks unsuspended"
fi

# 2. Check if Bluetooth sink exists
echo "[startup] Checking for Bluetooth audio sink..."
BT_SINK_COUNT=$(check_bluetooth_sink)

if [ "$BT_SINK_COUNT" -eq 0 ]; then
    echo "[startup] ⚠️  WARNING: No Bluetooth sink found!"
    echo "[startup] Attempting to force PulseAudio Bluetooth discovery..."
    
    # Get Bluetooth MAC from env or use default
    BT_MAC="${BLUETOOTH_SPEAKER_MAC:-E0:C8:22:85:F8:32}"
    
    # Force reload Bluetooth modules
    pactl unload-module module-bluetooth-discover 2>/dev/null
    pactl unload-module module-bluez5-discover 2>/dev/null
    sleep 1
    
    MODULE_ID=$(pactl load-module module-bluez5-discover 2>/dev/null)
    if [ -n "$MODULE_ID" ]; then
        echo "[startup] Bluetooth discovery module loaded (ID: $MODULE_ID)"
    fi
    
    # CRITICAL: Disconnect and reconnect Bluetooth to force sink creation
    echo "[startup] Forcing Bluetooth reconnection to create audio sink..."
    bluetoothctl disconnect "$BT_MAC" 2>/dev/null
    sleep 2
    
    # Reconnect
    echo "[startup] Reconnecting to $BT_MAC..."
    for i in {1..10}; do
        bluetoothctl connect "$BT_MAC" 2>/dev/null
        sleep 2
        
        # Check if connected
        if bluetoothctl info "$BT_MAC" | grep -q "Connected: yes"; then
            echo "[startup] ✓ Bluetooth device reconnected"
            break
        fi
        
        if [ $i -eq 10 ]; then
            echo "[startup] ❌ Failed to reconnect Bluetooth device"
        fi
    done
    
    # Wait for PulseAudio to create sink
    sleep 3
    
    # Check again
    BT_SINK_COUNT=$(check_bluetooth_sink)
    
    if [ "$BT_SINK_COUNT" -eq 0 ]; then
        echo "[startup] ❌ CRITICAL: Bluetooth sink still not available after module reload"
        echo "[startup] Attempting card profile switch..."
        
        # Try to switch card profile
        pactl set-card-profile bluez_card.* a2dp_sink 2>/dev/null
        sleep 2
        
        # Final check
        BT_SINK_COUNT=$(check_bluetooth_sink)
        
        if [ "$BT_SINK_COUNT" -eq 0 ]; then
            echo "[startup] ❌ WARNING: Cannot recover Bluetooth audio sink"
            echo "[startup] Available sinks:"
            pactl list sinks short
            echo ""
            echo "[startup] Diagnostic information:"
            echo "[startup] Bluetooth cards:"
            pactl list cards short | grep -i bluez
            echo "[startup] Bluetooth connection status:"
            bluetoothctl info "$BT_MAC" | grep -E "(Connected|UUID)"
            echo ""
            echo "[startup] ⚠️  Continuing without Bluetooth audio - system will work but audio output may not function"
            echo "[startup] You can manually troubleshoot with: pactl list cards"
        fi
    fi
fi

echo "[startup] ✓ Audio check passed - Bluetooth sink available"

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
