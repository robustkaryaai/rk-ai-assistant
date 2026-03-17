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
if ! grep -q "$CURRENT_HOSTNAME" /etc/hosts; then
    echo "[startup] Fixing /etc/hosts for $CURRENT_HOSTNAME..."
    # Now that we have NOPASSWD, we can use standard sudo
    echo "127.0.1.1 $CURRENT_HOSTNAME $BT_NAME" | sudo tee -a /etc/hosts > /dev/null
fi

# ─── 1. Hardware Initialization ───────────────────────────
# Clean up and ensure Bluetooth agent is running every time.
echo "[startup] Step 2: Cleaning up old Bluetooth processes..."
sudo killall -9 bluetooth-agent bt-agent 2>/dev/null || true

# Find adapter
HCI_DEV="hci1"
if ! hciconfig $HCI_DEV &>/dev/null; then
    HCI_DEV="hci0"
fi
echo "[startup] Using Bluetooth Adapter: $HCI_DEV"

echo "[startup] Step 3: Powering up $HCI_DEV in BLE-ONLY mode..."
    # Force interface down to apply low-level changes
    sudo hciconfig $HCI_DEV down 2>/dev/null || true
    
    # Try using btmgmt (Modern way) to force LE and disable BR/EDR
    if command -v btmgmt &> /dev/null; then
        echo "[startup] Using btmgmt to force BLE-only settings..."
        sudo btmgmt -i $HCI_DEV power off &>/dev/null || true
        sudo btmgmt -i $HCI_DEV le on &>/dev/null || true
        sudo btmgmt -i $HCI_DEV bredr off &>/dev/null || true
        sudo btmgmt -i $HCI_DEV ssp off &>/dev/null || true
        sudo btmgmt -i $HCI_DEV bondable off &>/dev/null || true
        sudo btmgmt -i $HCI_DEV connectable on &>/dev/null || true
        sudo btmgmt -i $HCI_DEV discov on &>/dev/null || true
        sudo btmgmt -i $HCI_DEV power on &>/dev/null || true
    fi

    # Legacy fallbacks
    sudo hciconfig $HCI_DEV up 2>/dev/null || true
    sudo hciconfig $HCI_DEV name "$BT_NAME" 2>/dev/null || true
    sudo hciconfig $HCI_DEV class 0x000100 2>/dev/null || true
    sudo hciconfig $HCI_DEV sspmode 0 2>/dev/null || true
    sudo hciconfig $HCI_DEV auth 0 2>/dev/null || true
    sudo hciconfig $HCI_DEV piscan 2>/dev/null || true

echo "[startup] Step 4: Launching Auto-Pairing Agent & Provisioning Service..."
# Set PYTHONPATH so we can run modules
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Note: Agent is still run but won't be triggered much in BLE-only mode
if [ -f "$SCRIPT_DIR/rk_assistant/bt_agent.py" ]; then
    sudo PYTHONPATH="$SCRIPT_DIR" python3 "$SCRIPT_DIR/rk_assistant/bt_agent.py" &
    sleep 2
fi

# Start the BLE Provisioning Service (DBus-based)
if [ -f "$SCRIPT_DIR/rk_assistant/provisioning_service.py" ]; then
    echo "[startup] Launching BLE Provisioning Service..."
    sudo PYTHONPATH="$SCRIPT_DIR" python3 -u -m rk_assistant.provisioning_service &
    sleep 2
fi

# Start the Classic Bluetooth Server (Fallback)
# (Keeping this but it may not work if BR/EDR is disabled above)
if [ -f "$SCRIPT_DIR/rk_assistant/classic_bluetooth_server.py" ]; then
    echo "[startup] Launching Classic Bluetooth Server..."
    sudo PYTHONPATH="$SCRIPT_DIR" python3 -u -m rk_assistant.classic_bluetooth_server &
    sleep 1
fi

echo "[startup] Step 5: Finalizing Bluetooth visibility..."
sudo bluetoothctl << BTEOF &>/dev/null
power on
discoverable on
pairable off
agent NoInputNoOutput
default-agent
discoverable-timeout 0
BTEOF

sudo sdptool add SP 2>/dev/null || true

# ─── 1. Hardware Identity ─────────────────────────────────
if [ ! -f "/tmp/.bt_setup_done" ]; then
    echo "[startup] Step 1: Configuring Hardware Identity..."
    
    # Sync hostname
    if [ "$CURRENT_HOSTNAME" != "$BT_NAME" ]; then
        echo "[startup] Setting system hostname to $BT_NAME..."
        sudo hostnamectl set-hostname "$BT_NAME"
    fi

    touch /tmp/.bt_setup_done
    echo "[startup] Hardware initialization complete."
else
    echo "[startup] Hardware already initialized, skipping hostname/identity setup."
fi

# ─── 2. Background Tasks ──────────────────────────────────
echo "[startup] Step 6: Starting background monitors..."
# Auto-trust paired devices loop
(
  echo "[startup] Auto-trust monitor started."
  while true; do
    # Get list of paired devices and trust them
    bluetoothctl devices Paired 2>/dev/null | awk '{print $2}' | while read -r dev; do
        bluetoothctl trust "$dev" &>/dev/null
    done
    
    # Also save currently connected device
    bluetoothctl info 2>/dev/null | grep "Connected: yes" -B 10 | grep "Device" | awk '{print $2}' > "$PAIRING_FILE" 2>/dev/null
    sleep 10
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
