#!/bin/bash
# Configure ALSA to use bluez-alsa for all audio output
# Run this on the Raspberry Pi

set -e

echo "======================================"
echo "Configuring ALSA for bluez-alsa"
echo "======================================"
echo ""

# Get speaker MAC from environment or use default
SPEAKER_MAC="${BLUETOOTH_SPEAKER_MAC:-E0:C8:22:85:F8:32}"
SPEAKER_MAC_UNDERSCORE=$(echo "$SPEAKER_MAC" | tr ':' '_')

echo "Creating /etc/asound.conf for bluez-alsa output..."
echo "Speaker MAC: $SPEAKER_MAC"
echo ""

# Create system-wide ALSA config
sudo tee /etc/asound.conf > /dev/null << EOF
# ALSA configuration for BluezALSA
# Routes all audio output to Bluetooth speaker via bluez-alsa

pcm.!default {
    type plug
    slave.pcm {
        type bluealsa
        device "${SPEAKER_MAC}"
        profile "a2dp"
    }
}

ctl.!default {
    type bluealsa
}
EOF

echo "✓ /etc/asound.conf created"
echo ""

echo "Testing audio output..."
speaker-test -t wav -c 2 -l 1 2>/dev/null || echo "speaker-test not available, skipping test"
echo ""

echo "======================================"
echo "Configuration Complete!"
echo "======================================"
echo ""
echo "All ALSA audio (mpg123, espeak, etc.) will now"
echo "route through bluez-alsa to your Bluetooth speaker."
echo ""
echo "Restart rk-assistant service to test:"
echo "  sudo systemctl restart rk-assistant.service"
echo ""
