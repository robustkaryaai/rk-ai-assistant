#!/bin/bash
export XDG_RUNTIME_DIR=/run/user/1000
export PULSE_RUNTIME_PATH=/run/user/1000/pulse

SCRIPT_DIR="/home/raspberrypi/Documents/rk-ai-assistant-main"
PAIRING_FILE="$SCRIPT_DIR/.last_bt_device"

echo "[startup] Starting RK AI Assistant..."

# ─── 1. Bluetooth Setup ────────────────────────────────────
echo "[startup] Setting up Bluetooth..."

# Power on adapter (try hci0 then hci1)
for HCI in hci0 hci1; do
    if hciconfig $HCI &>/dev/null; then
        sudo hciconfig $HCI up 2>/dev/null && echo "[startup] $HCI is UP." && break
    fi
done

# Make discoverable + pairable via bluetoothctl
bluetoothctl << 'BTEOF' &>/dev/null
power on
discoverable on
pairable on
agent on
default-agent
BTEOF

# ── Confirm BT is now discoverable ─────────────────────────
sleep 1
if hciconfig 2>/dev/null | grep -q "ISCAN\|PSCAN\|SCAN"; then
    echo "[startup] ✓ Bluetooth is DISCOVERABLE — Pi should now appear on your phone's BT scan!"
elif bluetoothctl show 2>/dev/null | grep -q "Discoverable: yes"; then
    echo "[startup] ✓ Bluetooth is DISCOVERABLE — Pi should now appear on your phone's BT scan!"
else
    echo "[startup] ✗ Bluetooth may NOT be discoverable — check 'bluetoothctl show'"
fi

# Try to reconnect to last paired phone
if [ -f "$PAIRING_FILE" ]; then
    LAST_MAC=$(cat "$PAIRING_FILE" | tr -d '[:space:]')
    if [ -n "$LAST_MAC" ]; then
        echo "[startup] Reconnecting to last device: $LAST_MAC ..."
        timeout 8 bluetoothctl connect "$LAST_MAC" &>/dev/null && \
            echo "[startup] Reconnected to $LAST_MAC!" || \
            echo "[startup] Phone not nearby — continuing without BT connection."
    fi
else
    echo "[startup] No previous BT device. Waiting for new pairing..."
fi

# Monitor and save any new BT connections in background
(
  bluetoothctl --timeout 0 monitor 2>/dev/null | while read -r event; do
    if echo "$event" | grep -q "Connected: yes"; then
        MAC=$(echo "$event" | grep -oP '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}' | head -1)
        if [ -n "$MAC" ]; then
            echo "[startup] BT device connected: $MAC — saved."
            echo "$MAC" > "$PAIRING_FILE"
        fi
    fi
  done
) &

# ─── 2. Check for Updates ─────────────────────────────────
echo "[startup] Checking for updates..."
cd "$SCRIPT_DIR" || cd /home/raspberrypi/Documents/rk-ai-assistant-main
git fetch origin 2>/dev/null
LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse @{u} 2>/dev/null)

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[startup] Update found! Pulling..."
    git pull origin main
else
    echo "[startup] Up to date."
fi

# ─── 3. Start Application ─────────────────────────────────
VENV_DIR="$SCRIPT_DIR/venv"
ALT_VENV="/home/raspberrypi/rk-ai-assistant/rk-env"

if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
elif [ -d "$ALT_VENV" ]; then
    source "$ALT_VENV/bin/activate"
else
    echo "[startup] WARNING: No venv found."
fi

echo "[startup] Launching main.py..."
exec python3 -u -m rk_assistant.main
