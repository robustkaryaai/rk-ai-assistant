#!/usr/bin/env bash
# ==============================================================================
# RK AI Assistant V2 — Master Controller Script (All-in-One)
# Target: Raspberry Pi Zero W (512MB RAM, ARMv6)
# ==============================================================================

# Do NOT use set -e because bluetoothctl or amixer/pactl warnings can exit the script prematurely!
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ─── 0. Configuration & Environment ───────────────────────────
ENV_FILE="$SCRIPT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE" 2>/dev/null || true
    set +a
fi

REQUIRED_HCI="hci1"
SPEAKER_MAC="${BLUETOOTH_SPEAKER_MAC:-D0:78:1D:4F:F4:1E}"
CARD_NAME="bluez_card.${SPEAKER_MAC//:/_}"
SINK_NAME="bluez_sink.${SPEAKER_MAC//:/_}.a2dp_sink"

echo "=========================================================="
echo "🚀 [RK-MASTER] Starting RK AI Assistant V2 Master Controller"
echo "📶 [RK-MASTER] Target Bluetooth Adapter: $REQUIRED_HCI (Strict)"
echo "🔊 [RK-MASTER] Target Speaker MAC:      $SPEAKER_MAC"
echo "=========================================================="

# ─── 1. Bluetooth Pre-Flight ───────────────────────────────────
# Restart bluetoothd cleanly so hci1 gets a fresh slate on every boot/restart
echo "[bluetooth] Restarting bluetooth daemon..."
sudo systemctl restart bluetooth 2>/dev/null || true
sleep 2

# Unblock any rfkill soft-block (survives reboots on some kernels)
echo "[bluetooth] Unblocking rfkill..."
sudo rfkill unblock bluetooth 2>/dev/null || true
sleep 0.5

# ─── 2. System & Audio Optimization ───────────────────────────
echo "[optimize] Applying low-latency kernel & memory tuning..."
sudo sysctl -w vm.swappiness=10 >/dev/null 2>&1 || true
sudo sysctl -w vm.vfs_cache_pressure=50 >/dev/null 2>&1 || true

if [ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
    echo "performance" | sudo tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor >/dev/null 2>&1 || true
fi

# Stop heavy non-essential daemons to free precious RAM
sudo systemctl stop cups cups-browsed triggerhappy >/dev/null 2>&1 || true

# ─── 2. Strict Adapter Verification (hci1 ONLY) ───────────────
echo "[hardware] Verifying adapter $REQUIRED_HCI..."
if ! hciconfig | grep -q "$REQUIRED_HCI"; then
    echo "🚨 [FATAL] Adapter $REQUIRED_HCI is missing! hci0 is damaged and cannot be used."
    echo "🚨 [FATAL] Triggering system reboot in 3 seconds to recover USB bus..."
    sleep 3
    sudo reboot
    exit 1
fi

echo "[hardware] ✅ $REQUIRED_HCI is active."
sudo hciconfig "$REQUIRED_HCI" up 2>/dev/null || true
sudo hciconfig "$REQUIRED_HCI" sspmode 1 2>/dev/null || true
sudo hciconfig "$REQUIRED_HCI" piscan 2>/dev/null || true
sudo hciconfig "$REQUIRED_HCI" lm master 2>/dev/null || true

# ─── 3. Audio Lock Helper Function ────────────────────────────
lock_speaker_audio() {
    if command -v pacmd &>/dev/null; then
        pacmd set-card-profile "$CARD_NAME" a2dp_sink &>/dev/null || true
        pacmd set-default-sink "$SINK_NAME" &>/dev/null || true
        pacmd set-sink-volume "$SINK_NAME" 65536 &>/dev/null || true
        
        # Silence all non-speaker cards to prevent audio hijacking
        pacmd list-cards 2>/dev/null | grep 'bluez_card' | awk '{print $NF}' | while read -r card; do
            if [ "$card" != "$CARD_NAME" ]; then
                pacmd set-card-profile "$card" off &>/dev/null || true
            fi
        done
    fi
    # Force 100% volume on Master and Bluetooth sink
    pactl set-sink-volume @DEFAULT_SINK@ 100% &>/dev/null || true
    pactl set-source-volume @DEFAULT_SOURCE@ 100% &>/dev/null || true
    amixer sset Master 100% &>/dev/null || true
}

# ─── 4. Initial Speaker Connection ───────────────────────────
echo "[bluetooth] Pairing and connecting to $SPEAKER_MAC..."
bluetoothctl trust "$SPEAKER_MAC" &>/dev/null || true

if ! bluetoothctl info "$SPEAKER_MAC" 2>/dev/null | grep -q "Connected: yes"; then
    echo "[bluetooth] Attempting connection..."
    timeout 10 bluetoothctl connect "$SPEAKER_MAC" || true
fi

if bluetoothctl info "$SPEAKER_MAC" 2>/dev/null | grep -q "Connected: yes"; then
    echo "[bluetooth] ✅ Speaker connected."
else
    echo "[bluetooth] ⚠️ Speaker not connected yet. Background watchdog will keep retrying."
fi

lock_speaker_audio

# ─── 5. Background Self-Healing Watchdog ───────────────────────
# Runs in background to monitor hci1 and speaker connectivity
(
    echo "[watchdog] Background hardware watchdog started."
    FAIL_COUNT=0
    while true; do
        sleep 15
        
        # Check 1: Is hci1 still present? If dropped, reboot immediately.
        if ! hciconfig | grep -q "$REQUIRED_HCI"; then
            echo "🚨 [WATCHDOG] $REQUIRED_HCI disappeared from USB bus! Rebooting now..."
            sudo reboot
            exit 1
        fi

        # Check 2: Is speaker connected?
        if ! bluetoothctl info "$SPEAKER_MAC" 2>/dev/null | grep -q "Connected: yes"; then
            echo "[watchdog] ⚠️ Speaker disconnected. Reconnecting..."
            timeout 8 bluetoothctl connect "$SPEAKER_MAC" &>/dev/null || true
            
            if bluetoothctl info "$SPEAKER_MAC" 2>/dev/null | grep -q "Connected: yes"; then
                echo "[watchdog] ✅ Reconnected to speaker."
                lock_speaker_audio
                FAIL_COUNT=0
            else
                ((FAIL_COUNT++))
                if [ $FAIL_COUNT -ge 5 ]; then
                    echo "🚨 [WATCHDOG] Speaker reconnect failed 5 times. Power-cycling $REQUIRED_HCI..."
                    sudo hciconfig "$REQUIRED_HCI" down && sleep 2 && sudo hciconfig "$REQUIRED_HCI" up
                    FAIL_COUNT=0
                fi
            fi
        fi
    done
) &
WATCHDOG_PID=$!

# Trap clean exit on shutdown
cleanup() {
    echo -e "\n[RK-MASTER] Shutting down..."
    kill "$WATCHDOG_PID" 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

# ─── 6. Launch & Supervise Python V2 Assistant ─────────────────
echo "=========================================================="
echo "🎉 [RK-MASTER] System healthy. Launching Python Assistant..."
echo "=========================================================="

while true; do
    python3 -u "$SCRIPT_DIR/main.py"
    EXIT_CODE=$?
    echo "[RK-MASTER] Assistant process exited with code $EXIT_CODE. Restarting in 3 seconds..."
    sleep 3
done
