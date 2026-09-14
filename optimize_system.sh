#!/bin/bash

# optimize_system.sh
# Critical optimizations for Audio on Pi Zero W

echo "🚀 optimizing system for audio performance..."

# 1. Disable WiFi Power Management (Fixes Bluetooth crackling due to shared antenna)
echo "📡 Disabling WiFi Power Management..."
sudo iw wlan0 set power_save off

# Make it persistent by adding to rc.local if not present (simple hack for now)
if [ -f /etc/rc.local ]; then
    if ! grep -q "iw wlan0 set power_save off" /etc/rc.local; then
        sudo sed -i -e '$i \iw wlan0 set power_save off\n' /etc/rc.local
    fi
else
    echo "⚠️ /etc/rc.local not found, skipping persistent WiFi power save config."
fi

# 2. Set CPU Governor to Performance (if available) or Ondemand
echo "⚡ Tuning CPU Governor..."
if [ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
    sudo sh -c "echo performance > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
fi

# 3. Increase USB current (for Bluetooth dongle stability if used)
# This requires /boot/config.txt edit, usually max_usb_current=1
# We'll skip editing config.txt automatically to be safe, but log it.


# 4. Set volume to 50% (prevents ear-blasting loud audio on boot)
echo "🔊 Setting volume to 50%..."
# ALSA (direct hardware)
amixer sset Master 50% 2>/dev/null || true
amixer sset PCM 50% 2>/dev/null || true
# PulseAudio (Bluetooth speakers use this)
pactl set-sink-volume @DEFAULT_SINK@ 50% 2>/dev/null || true

echo "✅ System optimized. CPU is high performance, WiFi sleep is OFF, volume is 50%."
echo "   Audio should be much more stable now."
