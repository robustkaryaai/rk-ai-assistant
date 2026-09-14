#!/bin/bash
# rk_launcher.sh
# Lightweight launcher: sets up Bluetooth + audio, then starts the assistant.
# Called by systemd instead of start_rk.sh (which has a speaker-wait deadlock).

export XDG_RUNTIME_DIR=/run/user/1000
export PULSE_RUNTIME_PATH=/run/user/1000/pulse

SCRIPT_DIR="/home/raspberrypi/Documents/rk-ai-assistant"

# ─── Read speaker MAC from .env or use default ────────────────
SPEAKER_MAC="D0:78:1D:4F:F4:1E"
ENV_FILE="$SCRIPT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    ENV_MAC=$(grep "^BLUETOOTH_SPEAKER_MAC=" "$ENV_FILE" | cut -d'=' -f2 | tr -d ' "' | tr -d "'")
    if [ -n "$ENV_MAC" ]; then
        SPEAKER_MAC="$ENV_MAC"
    fi
fi
BT_CARD="bluez_card.${SPEAKER_MAC//:/_}"
echo "[launcher] Speaker MAC: $SPEAKER_MAC"

# ─── Step 1: Ensure Bluetooth is powered on ───────────────────
echo "[launcher] Powering on Bluetooth..."
HCI_DEV="hci1"
if ! hciconfig | grep -q "hci1"; then
    HCI_DEV="hci0"
fi
sudo hciconfig "$HCI_DEV" up 2>/dev/null || true
sudo bluetoothctl <<'EOF' &>/dev/null
power on
discoverable on
pairable on
agent on
default-agent
discoverable-timeout 0
EOF

# ─── Step 2: Connect to speaker ───────────────────────────────
echo "[launcher] Connecting to speaker $SPEAKER_MAC..."
bluetoothctl connect "$SPEAKER_MAC" &>/dev/null || true
sleep 4

# ─── Step 3: Switch to HFP to enable mic ──────────────────────
echo "[launcher] Switching to HFP profile (mic + speaker)..."
pactl set-card-profile "$BT_CARD" headset-head-unit 2>/dev/null || \
pactl set-card-profile "$BT_CARD" headset-head-unit-cvsd 2>/dev/null || true
sleep 1

# ─── Step 4: Set default sink/source ─────────────────────────
BT_ID="${SPEAKER_MAC//:/_}"
pactl set-default-sink   "bluez_output.${BT_ID}.1" 2>/dev/null || true
pactl set-default-source "bluez_input.${BT_ID}.0"  2>/dev/null || true

# ─── Step 5: Set volume to 50% ────────────────────────────────
echo "[launcher] Setting volume to 50%..."
amixer sset Master 50% 2>/dev/null || true
amixer sset PCM    50% 2>/dev/null || true
pactl set-sink-volume @DEFAULT_SINK@ 50% 2>/dev/null || true

echo "[launcher] Audio setup complete. Launching RK AI..."

# ─── Step 6: Launch the assistant using venv python ───────────
cd "$SCRIPT_DIR"
exec "$SCRIPT_DIR/rk-ai-env/bin/python3" -u -m rk_assistant.main
