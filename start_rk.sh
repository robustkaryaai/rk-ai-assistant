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
    SOUND_DIR="$SCRIPT_DIR/rk_assistant/sounds"
    
    # Bump speaker volume up before talking
    echo "[startup] Maximizing audio volume..."
    amixer set Master 30%+ 2>/dev/null || amixer sset 'Master' 100% 2>/dev/null
    
    if command -v mpg123 &>/dev/null && [ -f "$SOUND_DIR/initializing.mp3" ]; then
        echo "[startup] Playing initializing.mp3 via mpg123..."
        mpg123 "$SOUND_DIR/initializing.mp3" >/dev/null 2>&1
    else
        echo "[startup] Warning: mpg123 not found or initializing.mp3 missing!"
    fi

    # D. Install Packages
    echo "[startup] Installing system dependencies for Audio & Voice..."
    sudo apt-get update && sudo apt-get install -y swig libpulse-dev libasound2-dev speex speexdsp-tools libspeexdsp-dev
    
    echo "[startup] Installing requirements.txt. This may take a while..."
    pip install -r "$SCRIPT_DIR/requirements.txt"
    
    ARCH=$(uname -m)

    # E. Download Vosk Model (if missing/supported)
    MODEL_DIR="$SCRIPT_DIR/rk_assistant/model"
    mkdir -p "$MODEL_DIR"
    
    if [ "$ARCH" != "armv6l" ]; then
        echo "[startup] Downloading Vosk model for offline STT..."
        if [ ! -d "$MODEL_DIR/vosk-model-small-en-us-0.15" ] && [ ! -d "$MODEL_DIR/vosk-model" ]; then
            echo "[startup] Fetching vosk-model-small-en-us-0.15.zip..."
            curl -L "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip" -o "$MODEL_DIR/vosk-model.zip"
            echo "[startup] Extracting Vosk model..."
            unzip -q -o "$MODEL_DIR/vosk-model.zip" -d "$MODEL_DIR/"
            rm -f "$MODEL_DIR/vosk-model.zip"
            mv "$MODEL_DIR/vosk-model-small-en-us-0.15" "$MODEL_DIR/vosk-model" 2>/dev/null || true
        fi

        # G. Install Piper TTS & Models (if missing)
        if ! command -v piper &> /dev/null && [ -f "$SCRIPT_DIR/install_piper.sh" ]; then
            echo "[startup] Piper TTS not found. Installing Piper and downloading voice models..."
            bash "$SCRIPT_DIR/install_piper.sh"
        fi
    else
        echo "[startup] Architecture ($ARCH) does not support Vosk/SmolLM/Piper natively. Skipping offline models."
    fi

    # H. Speak Ready
    if command -v mpg123 &>/dev/null && [ -f "$SOUND_DIR/pairing.mp3" ]; then
        echo "[startup] Playing pairing.mp3 via mpg123..."
        mpg123 "$SOUND_DIR/pairing.mp3" >/dev/null 2>&1
    fi
    
    touch "$FIRST_BOOT_FLAG"
    IS_FIRST_BOOT=1
    echo "[startup] === FIRST BOOT SETUP COMPLETE ==="
fi

# ─── 2. Standard Bluetooth Setup ───────────────────────────

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
if [ "$IS_FIRST_BOOT" = "1" ]; then
    exec python3 -u -m rk_assistant.main --first-boot
else
    exec python3 -u -m rk_assistant.main
fi
