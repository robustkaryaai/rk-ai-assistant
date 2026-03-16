#!/bin/bash
# ============================================================
# RK AI — Bluetooth Startup Script
# Runs on Pi boot, before main.py.
# 1) Makes Pi discoverable over BT
# 2) Tries to reconnect to last known paired phone
# 3) Starts main.py concurrently
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAIRING_FILE="$SCRIPT_DIR/.last_bt_device"
LOG_PREFIX="[rk_bt_startup]"

SLUG="000000000"
if [ -f "$SCRIPT_DIR/rk_assistant/slug.txt" ]; then
    SLUG=$(head -n1 "$SCRIPT_DIR/rk_assistant/slug.txt" | tr -d '[:space:]')
fi
BT_NAME="RK-AI-$SLUG"

echo "$LOG_PREFIX Starting RK AI Bluetooth Manager..."

# ─── Step 1: Ensure bluetooth service is running ───────────
if ! systemctl is-active --quiet bluetooth; then
    echo "$LOG_PREFIX bluetooth.service not active, starting it..."
    sudo systemctl start bluetooth
    sleep 2
fi

# ─── Step 2: Power on the adapter ──────────────────────────
# Try hci1 first (common for external/secondary), then hci0 (internal)
HCI_DEV="hci1"
if ! hciconfig $HCI_DEV &>/dev/null; then
    HCI_DEV="hci0"
fi

echo "$LOG_PREFIX Powering up $HCI_DEV..."
sudo hciconfig $HCI_DEV up 2>/dev/null || true
sleep 1

# ─── Step 3: Make discoverable and pairable ────────────────
echo "$LOG_PREFIX Setting adapter discoverable + pairable..."
sudo hciconfig $HCI_DEV class 0x000100 2>/dev/null || true
sudo bluetoothctl << 'EOF'
power on
discoverable on
pairable on
agent on
default-agent
EOF
echo "$LOG_PREFIX Pi is now discoverable as BT device."

# Also set a user-friendly alias that includes the device slug
sudo bluetoothctl system-alias "$BT_NAME" 2>/dev/null || true

# ─── Step 4: Try to reconnect to last paired phone ─────────
if [ -f "$PAIRING_FILE" ]; then
    LAST_MAC=$(cat "$PAIRING_FILE" | tr -d '[:space:]')
    if [ -n "$LAST_MAC" ]; then
        echo "$LOG_PREFIX Last paired device: $LAST_MAC — attempting reconnect..."
        # Try connecting (non-fatal if it fails — phone may not be nearby)
        timeout 10 bluetoothctl connect "$LAST_MAC" && \
            echo "$LOG_PREFIX Reconnected to $LAST_MAC!" || \
            echo "$LOG_PREFIX Could not reconnect (phone not nearby, that's OK)."
    fi
else
    echo "$LOG_PREFIX No previously paired device found. Waiting for new connection..."
fi

# ─── Step 5: Launch main.py in the background ──────────────
echo "$LOG_PREFIX Launching RK AI main.py in background..."
cd "$SCRIPT_DIR"
source venv/bin/activate
python -u -m rk_assistant.main &
MAIN_PID=$!
echo "$LOG_PREFIX main.py started with PID=$MAIN_PID"

# ─── Step 6: Watch for new BT connections and save the MAC ─
# Use bluetoothctl to monitor events and save connected device MACs
bluetoothctl --timeout 0 monitor 2>/dev/null | while read -r line; do
    if echo "$line" | grep -q "Connected: yes"; then
        # Extract MAC address from the line (format: [BT ADDR] Connected: yes)
        MAC=$(echo "$line" | grep -oP '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}' | head -1)
        if [ -n "$MAC" ]; then
            echo "$LOG_PREFIX New BT connection from $MAC. Saving for auto-reconnect."
            echo "$MAC" > "$PAIRING_FILE"
        fi
    fi
done &

# ─── Keep script alive until main.py exits ─────────────────
wait $MAIN_PID
echo "$LOG_PREFIX main.py exited. Shutting down BT manager."
