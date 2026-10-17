#!/usr/bin/env bash
# ==============================================================================
# RK AI Assistant V2 — Low Memory & Audio Latency Tuning for Pi Zero W (512MB RAM)
# ==============================================================================

set -e

echo "============================================="
echo "[optimize] Tuning Pi Zero W Performance..."
echo "============================================="

# 1. Swappiness Tuning (Minimize swapping to prevent audio skips)
sudo sysctl -w vm.swappiness=10
sudo sysctl -w vm.vfs_cache_pressure=50

# 2. CPU Governor to Performance (Lock 1GHz clock to avoid throttling audio)
if [ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
    echo "performance" | sudo tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor > /dev/null
    echo "[optimize] CPU Governor set to 'performance'."
fi

# 3. Audio & PulseAudio Buffer Tuning
if [ -f /etc/pulse/daemon.conf ]; then
    sudo sed -i 's/^; default-fragments =.*/default-fragments = 5/' /etc/pulse/daemon.conf 2>/dev/null || true
    sudo sed -i 's/^; default-fragment-size-msec =.*/default-fragment-size-msec = 25/' /etc/pulse/daemon.conf 2>/dev/null || true
fi

# 4. Disable unnecessary background daemons to save RAM
echo "[optimize] Disabling heavy background services..."
sudo systemctl stop cups cups-browsed triggerhappy 2>/dev/null || true
sudo systemctl disable cups cups-browsed triggerhappy 2>/dev/null || true

echo "[optimize] ✅ Pi Zero W optimized successfully for V2 audio playback."
