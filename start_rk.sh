#!/bin/bash
# RK AI Assistant Startup Script
# Optimized for stability and "Just Works" provisioning.

export XDG_RUNTIME_DIR=/run/user/1000
export PULSE_RUNTIME_PATH=/run/user/1000/pulse

SCRIPT_DIR="/home/raspberrypi/Documents/rk-ai-assistant-main"
PAIRING_FILE="$SCRIPT_DIR/.last_bt_device"
FIRST_BOOT_FLAG="$SCRIPT_DIR/.first_boot_done"

# Get slug
SLUG="000000000"
if [ -f "$SCRIPT_DIR/rk_assistant/slug.txt" ]; then
    SLUG=$(head -n1 "$SCRIPT_DIR/rk_assistant/slug.txt" | tr -d '[:space:]')
fi
BT_NAME="RK-AI-$SLUG"

echo "[startup] Starting RK AI Assistant ($BT_NAME)..."

# ─── 0. Hostname & Sudo Fix ────────────────────────────────
# Fix /etc/hosts to prevent 'unable to resolve host' delay/errors.
# We do this as the very first sudo command.
CURRENT_HOSTNAME=$(hostname)
if ! grep -q "$CURRENT_HOSTNAME" /etc/hosts; then
    echo "[startup] Fixing /etc/hosts for $CURRENT_HOSTNAME..."
    # Add to hosts file if missing. We use a temp file to avoid sudo delays during piping.
    echo "127.0.1.1\t$CURRENT_HOSTNAME $BT_NAME" > /tmp/hosts_fix
    sudo sh -c "cat /tmp/hosts_fix >> /etc/hosts"
fi

# ─── 1. Identity & Bluetooth Setup ────────────────────────
# We only do hardware reset once per boot to prevent service loop issues.
if [ ! -f "/tmp/.bt_setup_done" ]; then
    echo "[startup] Configuring hardware identity..."
    
    # Sync hostname if it changed
    if [ "$CURRENT_HOSTNAME" != "$BT_NAME" ]; then
        sudo hostnamectl set-hostname "$BT_NAME"
    fi

    # Kill old agents
    sudo killall -9 bluetooth-agent 2>/dev/null || true
    sudo killall -9 bt-agent 2>/dev/null || true
    sudo killall -9 python3 rk_assistant/bt_agent.py 2>/dev/null || true

    # Find adapter (prefer hci1)
    HCI_DEV="hci1"
    if ! hciconfig $HCI_DEV &>/dev/null; then
        HCI_DEV="hci0"
    fi

    echo "[startup] Configuring Bluetooth on $HCI_DEV..."
    sudo hciconfig $HCI_DEV up 2>/dev/null || true
    sudo hciconfig $HCI_DEV name "$BT_NAME" 2>/dev/null || true
    sudo hciconfig $HCI_DEV class 0x000100 2>/dev/null || true
    sudo hciconfig $HCI_DEV sspmode 1 2>/dev/null || true
    sudo hciconfig $HCI_DEV auth 0 2>/dev/null || true
    sudo hciconfig $HCI_DEV piscan 2>/dev/null || true

    # Start our "Yes-Man" Agent in background
    if [ -f "$SCRIPT_DIR/rk_assistant/bt_agent.py" ]; then
        sudo python3 "$SCRIPT_DIR/rk_assistant/bt_agent.py" &
        sleep 2
    fi

    # Lock in visibility
    sudo bluetoothctl << BTEOF &>/dev/null
power on
discoverable on
pairable on
discoverable-timeout 0
BTEOF

    sudo sdptool add SP 2>/dev/null || true
    touch /tmp/.bt_setup_done
    echo "[startup] Hardware identity configured."
fi

# ─── 2. Background Connection Monitor ─────────────────────
# Periodically check for connections to log paired devices
(
  while true; do
    bluetoothctl info | grep "Connected: yes" -B 10 | grep "Device" | awk '{print $2}' > "$PAIRING_FILE"
    sleep 30
  done
) &

# ─── 3. Update Check (Non-blocking) ───────────────────────
echo "[startup] Checking for updates..."
(
    cd "$SCRIPT_DIR" || exit
    git fetch origin 2>/dev/null
    LOCAL=$(git rev-parse HEAD 2>/dev/null)
    REMOTE=$(git rev-parse @{u} 2>/dev/null)
    if [ "$LOCAL" != "$REMOTE" ] && [ -n "$REMOTE" ]; then
        echo "[startup] New update found. Pulling..."
        git pull origin main
    fi
) &

# ─── 4. Launch Application ────────────────────────────────
VENV_DIR="$SCRIPT_DIR/venv"
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
fi

echo "[startup] Launching main.py..."
# If first boot flag exists, it's NOT first boot anymore.
if [ -f "$FIRST_BOOT_FLAG" ]; then
    exec python3 -u -m rk_assistant.main
else
    # No flag file = First boot
    exec python3 -u -m rk_assistant.main --first-boot
fi
