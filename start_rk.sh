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

# Avoid duplicate launches when another RK AI main.py is already running.
if pgrep -f "rk_assistant.main" >/dev/null 2>&1; then
    echo "[startup] RK AI main.py is already running. Skipping duplicate start."
    exit 0
fi

# ─── 0. Auto-Update (Blocking) ────────────────────────────
echo "[startup] Checking for updates..."
(
    cd "$SCRIPT_DIR" || exit
    # Git Health Check
    if ! git rev-parse HEAD >/dev/null 2>&1; then
        echo "[startup] Git corruption detected. Attempting recovery..."
        find .git/objects/ -type f -empty -delete 2>/dev/null
        git fetch --all 2>/dev/null
        git reset --hard origin/main 2>/dev/null
    fi
    git fetch origin 2>/dev/null
    LOCAL=$(git rev-parse HEAD 2>/dev/null)
    REMOTE=$(git rev-parse @{u} 2>/dev/null)
    if [ "$LOCAL" != "$REMOTE" ] && [ -n "$REMOTE" ]; then
        echo "[startup] Update found! Pulling latest changes..."
        git pull origin main 2>/dev/null
        # If this script itself was updated, we should restart it
        # but for now, we'll just continue as most logic is in Python
    else
        echo "[startup] System is up to date."
    fi
)


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
# Step 2: Adapter Check
HCI_DEV="hci1"
if ! hciconfig | grep -q "$HCI_DEV"; then
    HCI_DEV="hci0"
fi
echo "[startup] Using Bluetooth Adapter: $HCI_DEV"

# Legacy fallbacks & Identity
sudo hciconfig $HCI_DEV up 2>/dev/null || true
sudo hciconfig $HCI_DEV name "$BT_NAME" 2>/dev/null || true
# Set class to Computer/Audio (0x20041C) to allow both Sink and Source
sudo hciconfig $HCI_DEV class 0x20041C 2>/dev/null || true
sudo hciconfig $HCI_DEV sspmode 1 2>/dev/null || true
sudo hciconfig $HCI_DEV auth 0 2>/dev/null || true
sudo hciconfig $HCI_DEV piscan 2>/dev/null || true
# Ensure page scan and inquiry scan are on for classic discovery/connection
sudo hciconfig $HCI_DEV pscan 2>/dev/null || true
sudo hciconfig $HCI_DEV iscan 2>/dev/null || true
# Force master mode for classic connections (helps with speakers)
sudo hciconfig $HCI_DEV lm master 2>/dev/null || true

echo "[startup] Step 4: Launching Auto-Pairing Agent & Provisioning Service..."
# Set PYTHONPATH so we can run modules
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

# Start the Yes-Man Agent (Crucial for speaker and phone "Just Works")
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
if [ -f "$SCRIPT_DIR/rk_assistant/classic_bluetooth_server.py" ]; then
    echo "[startup] Launching Classic Bluetooth Server..."
    sudo PYTHONPATH="$SCRIPT_DIR" python3 -u -m rk_assistant.classic_bluetooth_server &
    sleep 1
fi

echo "[startup] Step 5: Finalizing Bluetooth visibility..."
# Use bluetoothctl for power but DON'T override the Python agent
sudo bluetoothctl << BTEOF &>/dev/null
power on
discoverable on
pairable on
discoverable-timeout 0
BTEOF

sudo sdptool add SP 2>/dev/null || true

# ─── 1. Hardware Identity ─────────────────────────────────
if [ ! -f "/tmp/.bt_setup_done" ]; then
    # Removed noisy logs
    if command -v hostnamectl &> /dev/null; then
        sudo hostnamectl set-hostname "$BT_NAME"
    fi
    sudo touch "/tmp/.bt_setup_done"
fi


# ─── 2. Background Tasks ──────────────────────────────────
echo "[startup] Step 6: Starting background monitors..."

# Helper: Force audio routing to speaker and silence any phone cards
lock_speaker_audio() {
    local SPEAKER_MAC="$1"
    local CARD_NAME="bluez_card.${SPEAKER_MAC//:/_}"
    local SINK_NAME="bluez_sink.${SPEAKER_MAC//:/_}.a2dp_sink"

    # 1. Set speaker profile and default sink
    pacmd set-card-profile "$CARD_NAME" a2dp_sink &>/dev/null || true
    sleep 0.5
    pacmd set-default-sink "$SINK_NAME" &>/dev/null || true

    # 2. Silence ALL other BT cards (phones, tablets, etc)
    pacmd list-cards 2>/dev/null | grep 'bluez_card' | awk '{print $NF}' | while read -r card; do
        if [ "$card" != "$CARD_NAME" ]; then
            echo "[startup] 🔇 Setting non-speaker card $card to 'off'"
            pacmd set-card-profile "$card" off &>/dev/null || true
        fi
    done
}

# Auto-trust and Speaker Reconnect loop
(
  echo "[startup] Bluetooth monitor started."
  
  # Load SPEAKER_MAC from .env if available
  SPEAKER_MAC="D0:78:1D:4F:F4:1E" # Default
  ENV_FILE="$SCRIPT_DIR/.env"
  if [ -f "$ENV_FILE" ]; then
      ENV_MAC=$(grep "^BLUETOOTH_SPEAKER_MAC=" "$ENV_FILE" | cut -d'=' -f2 | tr -d ' "' | tr -d "'")
      if [ -n "$ENV_MAC" ]; then
          SPEAKER_MAC="$ENV_MAC"
      fi
  fi
  echo "[startup] Monitoring Speaker MAC: $SPEAKER_MAC"

  # Ensure speaker isn't stuck in a "connect/disconnect" loop by checking state
  REBOOT_COUNT=0
  while true; do
    # 1. Trust all paired devices
    bluetoothctl devices Paired 2>/dev/null | awk '{print $2}' | while read -r dev; do
        bluetoothctl trust "$dev" &>/dev/null
    done
    
    # 2. Try reconnecting to speaker if disconnected
    if ! bluetoothctl info "$SPEAKER_MAC" 2>/dev/null | grep -q "Connected: yes"; then
        echo "[startup] Speaker $SPEAKER_MAC disconnected. Reclaiming..."
        
        # If we fail 5 times, try a "Nuclear Remove" to force a fresh pair
        if [ $REBOOT_COUNT -ge 3 ]; then
            echo "[startup] 🚨 Connection failed 3 times. Rebooting system..."
            sudo reboot
        fi

        bluetoothctl trust "$SPEAKER_MAC" &>/dev/null
        # Force disconnect first to clear "InProgress" or "Busy" errors
        bluetoothctl disconnect "$SPEAKER_MAC" &>/dev/null
        sleep 1
        
        # Aggressive connect
        # Use timeout to prevent hanging the loop
        timeout 10 bluetoothctl connect "$SPEAKER_MAC" &>/dev/null
        sleep 5
        
        if bluetoothctl info "$SPEAKER_MAC" 2>/dev/null | grep -q "Connected: yes"; then
            echo "[startup] Bluetooth connected to $SPEAKER_MAC."
            REBOOT_COUNT=0
            # Lock audio to speaker and silence phone cards
            lock_speaker_audio "$SPEAKER_MAC"
            # Signal that we have a speaker
            touch "/tmp/.speaker_ready"
        else
            echo "[startup] ❌ Connection failed. Retrying ($((REBOOT_COUNT+1))/3)..."
            ((REBOOT_COUNT++))
            rm -f "/tmp/.speaker_ready"
        fi
    else
        # Already connected — still enforce audio lock every cycle to prevent phones stealing sink
        lock_speaker_audio "$SPEAKER_MAC"
        touch "/tmp/.speaker_ready"
        REBOOT_COUNT=0
    fi
    
    sleep 30 # Check every 30s
  done
) &

# ─── 3. Launching Python Application ──────────────────────
echo "[startup] Step 7: Preparing Python environment..."
# WAIT FOR SPEAKER BEFORE RUNNING MAIN.PY
echo "[startup] Waiting for speaker sink..."
MAX_WAIT=60
WAIT_TIME=0
while [ ! -f "/tmp/.speaker_ready" ] && [ $WAIT_TIME -lt $MAX_WAIT ]; do
    sleep 2
    ((WAIT_TIME+=2))
done

if [ ! -f "/tmp/.speaker_ready" ]; then
    echo "[startup] 🚨 ERROR: Speaker not ready after 60s. Refusing to start main.py."
    exit 1
fi

VENV_DIR="$SCRIPT_DIR/rk-ai-env"
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
