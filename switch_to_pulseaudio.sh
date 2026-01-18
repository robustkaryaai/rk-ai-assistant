#!/bin/bash
# Switch from bluez-alsa back to PulseAudio
# This provides simpler audio routing

set -e

echo "======================================"
echo "Switching to PulseAudio"
echo "======================================"
echo ""

echo "1. Stopping bluez-alsa services..."
sudo systemctl stop bluealsa bluealsa-aplay 2>/dev/null || true
sudo systemctl disable bluealsa bluealsa-aplay 2>/dev/null || true
echo "   ✓ bluez-alsa stopped and disabled"
echo ""

echo "2. Re-enabling PulseAudio..."
systemctl --user unmask pulseaudio.socket 2>/dev/null || true
systemctl --user unmask pulseaudio.service 2>/dev/null || true
echo "   ✓ PulseAudio unmasked"
echo ""

echo "3. Removing ALSA config..."
sudo rm -f /etc/asound.conf
echo "   ✓ /etc/asound.conf removed"
echo ""

echo "4. Starting PulseAudio..."
pulseaudio --kill 2>/dev/null || true
sleep 1
pulseaudio --start --exit-idle-time=-1
sleep 2
echo "   ✓ PulseAudio started"
echo ""

echo "5. Loading Bluetooth modules..."
pactl load-module module-bluez5-discover 2>/dev/null || echo "   Module already loaded"
sleep 2
echo "   ✓ Bluetooth module loaded"
echo ""

echo "======================================"
echo "Switch Complete!"
echo "======================================"
echo ""
echo "PulseAudio is now handling Bluetooth audio."
echo "The system will:"
echo "  1. Connect to Bluetooth speaker"
echo "  2. Create PulseAudio sink automatically"
echo "  3. Unsuspend if needed"
echo "  4. Set as default"
echo ""
echo "Restart rk-assistant service:"
echo "  sudo systemctl restart rk-assistant.service"
echo ""
