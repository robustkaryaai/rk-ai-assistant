#!/bin/bash
export XDG_RUNTIME_DIR=/run/user/1000
export PULSE_RUNTIME_PATH=/run/user/1000/pulse

echo "[startup] Starting RK AI Assistant..."

# 1. Check Bluetooth (hci1)
echo "[startup] Checking Bluetooth adapter (hci1)..."
if ! hciconfig hci1 | grep -q "UP"; then
    echo "[startup] Bluetooth adapter is DOWN. Attempting to bring up..."
    sudo hciconfig hci1 up
    sleep 2
fi

if hciconfig hci1 | grep -q "UP"; then
    echo "[startup] Bluetooth adapter is UP."
else
    echo "[startup] WARNING: Bluetooth adapter hci1 not found or down!"
fi

# 2. Check for Updates
echo "[startup] Checking for updates..."
cd /home/raspberrypi/rk-ai-assistant
git fetch origin
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse @{u})

if [ $LOCAL != $REMOTE ]; then
    echo "[startup] Update found! Pulling changes..."
    git pull origin main
    echo "[startup] Update complete."
else
    echo "[startup] System is up to date."
fi

# 3. Start Application
echo "[startup] Launching main.py..."
export DISPLAY=:0

# Ensure we use the correct virtual environment
VENV_DIR="/home/raspberrypi/rk-ai-assistant/rk-env"

if [ -d "$VENV_DIR" ]; then
    echo "[startup] Activating virtual environment: $VENV_DIR"
    source "$VENV_DIR/bin/activate"
    
    # Dependency check skipped by user request
    # Check/Install critical dependencies
    # if ! python3 -c "import audioop_lts, dbus, gi" &> /dev/null; then
    #     echo "[startup] Missing critical dependencies (audioop_lts, dbus, or gi)."
    #     echo "[startup] Installing from requirements.txt..."
    #     pip install -r requirements.txt
    # fi
else
    echo "[startup] WARNING: rk-env not found. Creating one..."
    python3 -m venv rk-env
    source rk-env/bin/activate
    # pip install -r requirements.txt
fi

exec python3 -m rk_assistant.main
