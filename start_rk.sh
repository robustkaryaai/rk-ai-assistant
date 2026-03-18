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
  FAIL_COUNT=0
  while true; do
    # 1. Trust all paired devices
    bluetoothctl devices Paired 2>/dev/null | awk '{print $2}' | while read -r dev; do
        bluetoothctl trust "$dev" &>/dev/null
    done
    
    # 2. Try reconnecting to speaker if disconnected
    if ! bluetoothctl info "$SPEAKER_MAC" 2>/dev/null | grep -q "Connected: yes"; then
        echo "[startup] Speaker $SPEAKER_MAC disconnected. Reclaiming..."
        
        # If we fail 5 times, try a "Nuclear Remove" to force a fresh pair
        if [ $FAIL_COUNT -ge 5 ]; then
            echo "[startup] 🚨 Connection stuck. Forcing device removal and adapter reset..."
            bluetoothctl remove "$SPEAKER_MAC" &>/dev/null
            sudo hciconfig $HCI_DEV down && sleep 2 && sudo hciconfig $HCI_DEV up
            sudo hciconfig $HCI_DEV class 0x20041C
            FAIL_COUNT=0
            sleep 5
            # Since we removed it, we need to scan and re-pair if the agent is running
            # but usually, just restarting the service is better here.
            echo "[startup] Device removed. Please ensure speaker is in pairing mode."
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
            echo "[startup] Bluetooth connected. Verifying audio sink..."
            sleep 4
            
            # 1. Check if PulseAudio sees the bluez sink
            SINK_NAME="bluez_sink.${SPEAKER_MAC//:/_}.a2dp_sink"
            if pacmd list-sinks | grep -q "name: <$SINK_NAME>"; then
                # 2. Try a "Silent Ping" to the sink to verify it's actually responding
                # If the sink is "fake", this will usually hang or fail.
                if timeout 2 paplay --device="$SINK_NAME" --raw --channels=1 --rate=44100 /dev/zero &>/dev/null; then
                    echo "[startup] ✓ Audio sink verified and responding. Connected to $SPEAKER_MAC."
                    FAIL_COUNT=0
                    pacmd set-default-sink "$SINK_NAME" &>/dev/null || true
                else
                    echo "[startup] ⚠️ Sink found but not responding. Forcing profile reset..."
                    CARD_NAME="bluez_card.${SPEAKER_MAC//:/_}"
                    pacmd set-card-profile "$CARD_NAME" off &>/dev/null
                    sleep 1
                    pacmd set-card-profile "$CARD_NAME" a2dp_sink &>/dev/null
                    sleep 2
                    if timeout 2 paplay --device="$SINK_NAME" --raw --channels=1 --rate=44100 /dev/zero &>/dev/null; then
                        echo "[startup] ✓ Sink recovered. Connected to $SPEAKER_MAC."
                        FAIL_COUNT=0
                    else
                        echo "[startup] ❌ Sink still dead. Disconnecting..."
                        bluetoothctl disconnect "$SPEAKER_MAC" &>/dev/null
                        ((FAIL_COUNT++))
                    fi
                fi
            else
                echo "[startup] ⚠️ Connected but no audio sink found. Forcing profile..."
                CARD_NAME="bluez_card.${SPEAKER_MAC//:/_}"
                pacmd set-card-profile "$CARD_NAME" a2dp_sink &>/dev/null || true
                sleep 2
                if pacmd list-sinks | grep -q "name: <$SINK_NAME>"; then
                    echo "[startup] ✓ Profile fixed. Connected to $SPEAKER_MAC."
                    FAIL_COUNT=0
                else
                    echo "[startup] ❌ Fake connection detected (No Sink). Disconnecting..."
                    bluetoothctl disconnect "$SPEAKER_MAC" &>/dev/null
                    ((FAIL_COUNT++))
                fi
            fi
        else
            echo "[startup] ❌ Connection failed (org.bluez.Error). Retrying ($((FAIL_COUNT+1))/5)..."
            ((FAIL_COUNT++))
        fi
    else
        FAIL_COUNT=0
    fi

    # 3. Stay-Alive Pulse (Prevents auto-shutdown)
    # Every 2 minutes, play a 0.5s silent tone
    if command -v paplay &> /dev/null; then
        (head -c 4000 /dev/zero | paplay --raw --channels=1 --rate=44100 &>/dev/null) &
    fi
    
    sleep 60 # Check more frequently (every minute)
  done
) &

# Update check (Non-blocking with corruption recovery)
(
    cd "$SCRIPT_DIR" || exit
    
    # Git Health Check: Fix corrupt objects if any
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
        echo "[startup] Update available. Pulling..."
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
