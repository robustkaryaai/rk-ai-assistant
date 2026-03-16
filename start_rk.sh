#!/bin/bash
# RK AI Assistant Startup Script - STABILITY VERSION
# This script is designed to fail fast, log everything, and avoid sudo deadlocks.

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

echo "[startup] --- STARTING RK AI STARTUP SEQUENCE ---"
echo "[startup] Target Name: $BT_NAME"

# ─── 0. Hostname & Sudo Deadlock Fix ──────────────────────
# Fix /etc/hosts IMMEDIATELY to stop sudo from hanging.
CURRENT_HOSTNAME=$(hostname)
echo "[startup] Current Hostname: $CURRENT_HOSTNAME"

# Add entry to /etc/hosts if missing to prevent sudo delay
# We do this without sudo first to a temp file
if ! grep -q "$CURRENT_HOSTNAME" /etc/hosts; then
    echo "[startup] Fixing /etc/hosts for $CURRENT_HOSTNAME..."
    # Create entry
    echo "127.0.1.1 $CURRENT_HOSTNAME $BT_NAME" > /tmp/hosts_entry
    # Try to append with sudo -n (non-blocking)
    sudo -n sh -c "cat /tmp/hosts_entry >> /etc/hosts" 2>/dev/null
    rm -f /tmp/hosts_entry
fi

# ─── 1. Hardware Initialization ───────────────────────────
# Only do this once per boot to prevent service loops.
if [ ! -f "/tmp/.bt_setup_done" ]; then
    echo "[startup] Step 1: Configuring Hardware Identity..."
    
    # Sync hostname
    if [ "$CURRENT_HOSTNAME" != "$BT_NAME" ]; then
        echo "[startup] Setting system hostname to $BT_NAME..."
        sudo -n hostnamectl set-hostname "$BT_NAME" 2>/dev/null
    fi

    echo "[startup] Step 2: Cleaning up old Bluetooth processes..."
    sudo -n killall -9 bluetooth-agent bt-agent 2>/dev/null || true
    
    # Find adapter
    HCI_DEV="hci1"
    if ! hciconfig $HCI_DEV &>/dev/null; then
        HCI_DEV="hci0"
    fi
    echo "[startup] Using Bluetooth Adapter: $HCI_DEV"

    echo "[startup] Step 3: Powering up $HCI_DEV..."
    sudo -n hciconfig $HCI_DEV up 2>/dev/null || true
    sudo -n hciconfig $HCI_DEV name "$BT_NAME" 2>/dev/null || true
    sudo -n hciconfig $HCI_DEV class 0x000100 2>/dev/null || true
    sudo -n hciconfig $HCI_DEV sspmode 1 2>/dev/null || true
    sudo -n hciconfig $HCI_DEV auth 0 2>/dev/null || true
    sudo -n hciconfig $HCI_DEV piscan 2>/dev/null || true

    echo "[startup] Step 4: Launching Auto-Pairing Agent..."
    if [ -f "$SCRIPT_DIR/rk_assistant/bt_agent.py" ]; then
        sudo -n python3 "$SCRIPT_DIR/rk_assistant/bt_agent.py" &
        sleep 2
    fi

    echo "[startup] Step 5: Finalizing Bluetooth visibility..."
    # Timeout bluetoothctl to prevent hangs
    timeout 5s sudo -n bluetoothctl << BTEOF &>/dev/null
power on
discoverable on
pairable on
discoverable-timeout 0
BTEOF

    sudo -n sdptool add SP 2>/dev/null || true
    touch /tmp/.bt_setup_done
    echo "[startup] Hardware initialization complete."
else
    echo "[startup] Hardware already initialized, skipping setup."
fi

# ─── 2. Background Tasks ──────────────────────────────────
echo "[startup] Step 6: Starting background monitors..."
(
  while true; do
    bluetoothctl info 2>/dev/null | grep "Connected: yes" -B 10 | grep "Device" | awk '{print $2}' > "$PAIRING_FILE" 2>/dev/null
    sleep 60
  done
) &

# Update check (Non-blocking)
(
    cd "$SCRIPT_DIR" || exit
    git fetch origin 2>/dev/null
    LOCAL=$(git rev-parse HEAD 2>/dev/null)
    REMOTE=$(git rev-parse @{u} 2>/dev/null)
    if [ "$LOCAL" != "$REMOTE" ] && [ -n "$REMOTE" ]; then
        echo "[startup] Update available. Pulling in background..."
        git pull origin main 2>/dev/null
    fi
) &

# ─── 3. Launching Python Application ──────────────────────
echo "[startup] Step 7: Preparing Python environment..."
VENV_DIR="$SCRIPT_DIR/venv"
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
fi

# Final check for main.py
if [ ! -f "$SCRIPT_DIR/rk_assistant/main.py" ]; then
    echo "[startup] ERROR: main.py not found at $SCRIPT_DIR/rk_assistant/main.py"
    exit 1
fi

echo "[startup] Step 8: Launching main.py..."
# If first boot flag exists, it's NOT first boot anymore.
if [ -f "$FIRST_BOOT_FLAG" ]; then
    echo "[startup] Mode: Standard Boot"
    exec python3 -u -m rk_assistant.main
else
    echo "[startup] Mode: First Boot"
    exec python3 -u -m rk_assistant.main --first-boot
fi

echo "[startup] ERROR: exec failed!"
exit 1
