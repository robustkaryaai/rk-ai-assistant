#!/bin/bash
# Switch from bluez-alsa back to PulseAudio
# Optimized for Pi Zero W (Low Latency / Glitch Free)

set -e

echo "======================================"
echo "Switching to PulseAudio (Optimized)"
echo "======================================"
echo ""

# 1. Stop BlueALSA
echo "1. Stopping bluez-alsa services..."
sudo systemctl stop bluealsa bluealsa-aplay 2>/dev/null || true
sudo systemctl disable bluealsa bluealsa-aplay 2>/dev/null || true
echo "   ✓ bluez-alsa stopped and disabled"

# 2. Configure PulseAudio for Low CPU / Latency
echo "2. Configuring PulseAudio..."
sudo sed -i 's/; resample-method = speex-float-1/resample-method = trivial/g' /etc/pulse/daemon.conf
sudo sed -i 's/; default-sample-rate = 44100/default-sample-rate = 44100/g' /etc/pulse/daemon.conf
sudo sed -i 's/; alternate-sample-rate = 48000/alternate-sample-rate = 44100/g' /etc/pulse/daemon.conf
sudo sed -i 's/^load-module module-udev-detect$/load-module module-udev-detect tsched=0/g' /etc/pulse/default.pa

# Also allow user to run it
systemctl --user unmask pulseaudio.socket 2>/dev/null || true
systemctl --user unmask pulseaudio.service 2>/dev/null || true

# 3. Clean ALSA
echo "3. Removing ALSA config..."
sudo rm -f /etc/asound.conf
echo "   ✓ /etc/asound.conf removed"

# 4. Restart PulseAudio
echo "4. Starting PulseAudio..."
pulseaudio -k 2>/dev/null || true
sleep 1
pulseaudio --start --exit-idle-time=-1
sleep 2

# 5. Load Bluetooth Modules explicitly (sometimes needed)
if ! pactl list modules | grep -q "module-bluez5-discover"; then
    pactl load-module module-bluez5-discover 2>/dev/null || true
fi

echo "======================================"
echo "Switch Complete!"
echo "======================================"
echo "PulseAudio is now active with 'tsched=0' and 'trivial' resampling."
echo "Please restart the assistant: sudo systemctl restart rk-assistant.service"
