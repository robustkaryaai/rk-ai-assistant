#!/bin/bash
export XDG_RUNTIME_DIR=/run/user/1000
export PULSE_RUNTIME_PATH=/run/user/1000/pulse

SCRIPT_DIR="/home/raspberrypi/Documents/rk-ai-assistant-main"
PAIRING_FILE="$SCRIPT_DIR/.last_bt_device"
FIRST_BOOT_FLAG="$SCRIPT_DIR/.first_boot_done"

echo "[startup] Starting RK AI Assistant..."

# ─── 0. Hardware Prep ──────────────────────────────────────
sudo rfkill unblock bluetooth 2>/dev/null
for HCI in hci1 hci0; do
    if hciconfig $HCI &>/dev/null; then
        sudo hciconfig $HCI up 2>/dev/null && echo "[startup] $HCI is UP." && break
    fi
done

# ─── 1. First Boot Hook ────────────────────────────────────
if [ ! -f "$FIRST_BOOT_FLAG" ]; then
    echo "[startup] === FIRST BOOT DETECTED ==="
    
    # A. Scan for Custom Speaker (HBTS004) and connect
    echo "[startup] Looking for HBTS004 speaker..."
    bluetoothctl scan on &
    SCAN_PID=$!
    
    SPEAKER_MAC=""
    for i in {1..30}; do
        SPEAKER_MAC=$(bluetoothctl devices | grep -i "HBTS004" | awk '{print $2}' | head -n 1)
        if [ -n "$SPEAKER_MAC" ]; then
            echo "[startup] Found HBTS004 at $SPEAKER_MAC!"
            break
        fi
        sleep 2
    done
    
    kill $SCAN_PID 2>/dev/null
    bluetoothctl scan off 2>/dev/null
    
    if [ -n "$SPEAKER_MAC" ]; then
        echo "[startup] Pairing with $SPEAKER_MAC..."
        bluetoothctl pair "$SPEAKER_MAC"
        sleep 2
        bluetoothctl trust "$SPEAKER_MAC"
        sleep 1
        bluetoothctl connect "$SPEAKER_MAC"
        sleep 3
        echo "$SPEAKER_MAC" > "$PAIRING_FILE"
    else
        echo "[startup] WARNING: HBTS004 not found."
    fi

    # B. Venv Setup
    VENV_DIR="$SCRIPT_DIR/venv"
    if [ ! -d "$VENV_DIR" ]; then
        echo "[startup] Creating Python virtual environment..."
        python3 -m venv "$VENV_DIR"
    fi
    source "$VENV_DIR/bin/activate"

    # C. Speak Initializing Warning
    if command -v espeak &>/dev/null; then
        espeak -s 140 "Initializing R K A I. This may take up to 10 minutes."
    fi

    # D. Install Packages
    echo "[startup] Installing requirements.txt. This will take ~10 minutes..."
    pip install -r "$SCRIPT_DIR/requirements.txt"

    # E. Speak Ready
    if command -v espeak &>/dev/null; then
        espeak -s 140 "R K A I initialized. Entering pairing mode."
    fi
    
    touch "$FIRST_BOOT_FLAG"
    echo "[startup] === FIRST BOOT SETUP COMPLETE ==="
fi

# ─── 2. Standard Bluetooth Setup ───────────────────────────
echo "[startup] Normal Bluetooth config..."

# Extract slug to set BT Name
if [ -f "$SCRIPT_DIR/rk_assistant/slug.txt" ]; then
    SLUG=$(head -n 1 "$SCRIPT_DIR/rk_assistant/slug.txt" | grep -o "[a-zA-Z0-9\-]*" | head -n 1)
elif [ -f "$SCRIPT_DIR/.env" ] && grep -q "^DEVICE_SLUG=" "$SCRIPT_DIR/.env"; then
    SLUG=$(grep -oP "^DEVICE_SLUG=[\"']?\K[a-zA-Z0-9\-]+" "$SCRIPT_DIR/.env" | head -n 1)
else
    SLUG="Unknown"
fi

BT_NAME="RK-AI-$SLUG"
echo "[startup] Setting Bluetooth Name to: $BT_NAME"

sudo killall -9 bluetooth-agent 2>/dev/null
sudo killall -9 bt-agent 2>/dev/null

bluetoothctl << BTEOF &>/dev/null
power on
system-alias $BT_NAME
discoverable on
pairable on
BTEOF

if [ -f "$SCRIPT_DIR/rk_assistant/bt_agent.py" ]; then
    sudo python3 "$SCRIPT_DIR/rk_assistant/bt_agent.py" &
fi

if [ -f "$PAIRING_FILE" ]; then
    LAST_MAC=$(cat "$PAIRING_FILE" | tr -d '[:space:]')
    if [ -n "$LAST_MAC" ]; then
        timeout 8 bluetoothctl connect "$LAST_MAC" &>/dev/null
    fi
fi

(
  bluetoothctl --timeout 0 monitor 2>/dev/null | while read -r event; do
    if echo "$event" | grep -q "Connected: yes"; then
        MAC=$(echo "$event" | grep -oP '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}' | head -1)
        if [ -n "$MAC" ]; then
            echo "$MAC" > "$PAIRING_FILE"
        fi
    fi
  done
) &

# ─── 3. Check for Updates ─────────────────────────────────
cd "$SCRIPT_DIR" || cd /home/raspberrypi/Documents/rk-ai-assistant-main
git fetch origin 2>/dev/null
LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse @{u} 2>/dev/null)

if [ "$LOCAL" != "$REMOTE" ]; then
    git pull origin main
fi

# ─── 4. Start Application ─────────────────────────────────
VENV_DIR="$SCRIPT_DIR/venv"
ALT_VENV="/home/raspberrypi/rk-ai-assistant/rk-env"

if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
elif [ -d "$ALT_VENV" ]; then
    source "$ALT_VENV/bin/activate"
fi

echo "[startup] Launching main.py..."
exec python3 -u -m rk_assistant.main
