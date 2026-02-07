#!/bin/bash
# Installation script for bluez-alsa
# Replaces PulseAudio with bluez-alsa for Bluetooth audio

set -e  # Exit on error

echo "======================================"
echo "bluez-alsa Installation"
echo "======================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root: sudo ./install_bluez_alsa.sh"
    exit 1
fi

echo "1. Stopping PulseAudio..."
systemctl --user stop pulseaudio.socket 2>/dev/null || true
systemctl --user stop pulseaudio.service 2>/dev/null || true
killall pulseaudio 2>/dev/null || true
echo "   ✓ PulseAudio stopped"
echo ""

echo "2. Installing bluez-alsa..."
apt-get update
apt-get install -y bluez-alsa-utils
echo "   ✓ bluez-alsa installed"
echo ""

echo "3. Configuring bluez-alsa service..."
# Create systemd service for bluealsa
cat > /etc/systemd/system/bluealsa.service << 'EOF'
[Unit]
Description=BluezALSA proxy
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=simple
ExecStart=/usr/bin/bluealsa -p a2dp-sink --codec=sbc --keep-alive=5
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable bluealsa.service
systemctl start bluealsa.service
echo "   ✓ bluealsa service configured and started"
echo ""

echo "4. Creating bluealsa-aplay service for speaker..."
# Get speaker MAC from environment or use default
SPEAKER_MAC="${BLUETOOTH_SPEAKER_MAC:-E0:C8:22:85:F8:32}"

cat > /etc/systemd/system/bluealsa-aplay.service << EOF
[Unit]
Description=BlueALSA aplay for Bluetooth speaker
After=bluealsa.service bluetooth.service
Requires=bluealsa.service bluetooth.service

[Service]
Type=simple
ExecStart=/usr/bin/bluealsa-aplay --pcm-buffer-time=250000 ${SPEAKER_MAC}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable bluealsa-aplay.service
echo "   ✓ bluealsa-aplay service created (will start after Bluetooth connects)"
echo ""

echo "5. Disabling PulseAudio auto-start..."
systemctl --global mask pulseaudio.socket 2>/dev/null || true
systemctl --global mask pulseaudio.service 2>/dev/null || true
echo "   ✓ PulseAudio disabled"
echo ""

echo "======================================"
echo "Installation Complete!"
echo "======================================"
echo ""
echo "bluez-alsa is now installed and configured."
echo "Speaker MAC: $SPEAKER_MAC"
echo ""
echo "Next steps:"
echo "1. Reboot the system: sudo reboot"
echo "2. After reboot, bluealsa will handle all Bluetooth audio"
echo ""
echo "Useful commands:"
echo "  - Check bluealsa status: systemctl status bluealsa"
echo "  - Check aplay status: systemctl status bluealsa-aplay"
echo "  - List BT devices: bluealsa-aplay --list-devices"
echo ""
