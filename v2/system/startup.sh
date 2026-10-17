#!/usr/bin/env bash
# ==============================================================================
# RK AI Assistant V2 - Pi Zero W Hardware Startup Script
# Strict Requirements:
#   1. Adapter: hci1 ONLY. hci0 is damaged. If hci1 is missing -> REBOOT.
#   2. Speaker: D0:78:1D:4F:F4:1E strictly bound & locked.
#   3. Optimized for single-core ARMv6 (512MB RAM).
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

REQUIRED_HCI="hci1"
SPEAKER_MAC="${BLUETOOTH_SPEAKER_MAC:-D0:78:1D:4F:F4:1E}"
CARD_NAME="bluez_card.${SPEAKER_MAC//:/_}"
SINK_NAME="bluez_sink.${SPEAKER_MAC//:/_}.a2dp_sink"

echo "============================================="
echo "[startup] Initializing RK AI V2 Client..."
echo "[startup] Target Bluetooth Adapter: $REQUIRED_HCI"
echo "[startup] Target Speaker MAC:      $SPEAKER_MAC"
echo "============================================="

# ─── 1. STRICT ADAPTER ENFORCEMENT (NO HCI0 FALLBACK) ───
echo "[startup] Checking for adapter $REQUIRED_HCI..."
if ! hciconfig | grep -q "$REQUIRED_HCI"; then
    echo "🚨 [FATAL] Adapter $REQUIRED_HCI not found! hci0 is damaged and cannot be used."
    echo "🚨 [FATAL] Triggering immediate system reboot in 3 seconds to recover USB bus..."
    sleep 3
    sudo reboot
    exit 1
fi

echo "[startup] ✅ $REQUIRED_HCI is present."
sudo hciconfig "$REQUIRED_HCI" up
sudo hciconfig "$REQUIRED_HCI" sspmode 1 2>/dev/null || true
sudo hciconfig "$REQUIRED_HCI" piscan 2>/dev/null || true
sudo hciconfig "$REQUIRED_HCI" lm master 2>/dev/null || true

# ─── 2. SPEAKER CONNECTION & PROFILE LOCKING ────────────
echo "[startup] Ensuring Speaker $SPEAKER_MAC is trusted & connected..."
bluetoothctl trust "$SPEAKER_MAC" &>/dev/null || true

if ! bluetoothctl info "$SPEAKER_MAC" 2>/dev/null | grep -q "Connected: yes"; then
    echo "[startup] Speaker disconnected. Attempting to connect..."
    timeout 10 bluetoothctl connect "$SPEAKER_MAC" &>/dev/null || true
fi

# Lock audio sink if PulseAudio is running
if command -v pacmd &>/dev/null; then
    pacmd set-card-profile "$CARD_NAME" a2dp_sink &>/dev/null || true
    pacmd set-default-sink "$SINK_NAME" &>/dev/null || true
    
    # Silence any non-speaker devices to avoid interference
    pacmd list-cards 2>/dev/null | grep 'bluez_card' | awk '{print $NF}' | while read -r card; do
        if [ "$card" != "$CARD_NAME" ]; then
            pacmd set-card-profile "$card" off &>/dev/null || true
        fi
    done
fi

echo "[startup] System initialized successfully. Launching V2 Assistant..."
exec python3 "$SCRIPT_DIR/main.py"
