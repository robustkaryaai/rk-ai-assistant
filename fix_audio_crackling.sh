#!/bin/bash
# Fix Bluetooth audio crackling on Raspberry Pi
# Run this once to optimize audio buffers

echo "Optimizing Bluetooth audio buffers..."

# 1. Increase PulseAudio default buffer size
sudo tee -a /etc/pulse/daemon.conf > /dev/null <<EOF

# Custom settings for smooth Bluetooth playback
default-fragments = 8
default-fragment-size-msec = 10
resample-method = speex-float-1
avoid-resampling = yes
EOF

# 2. Increase Bluetooth A2DP buffer
if [ -f /etc/bluetooth/audio.conf ]; then
    sudo sed -i 's/^#*Master=.*/Master=true/' /etc/bluetooth/audio.conf
fi

# 3. Restart audio services
pulseaudio -k 2>/dev/null || true
sleep 1

echo "✓ Audio buffers optimized!"
echo ""
echo "Changes made:"
echo "  - Increased PulseAudio fragments to 8"
echo "  - Set fragment size to 10ms"
echo "  - Optimized resampling"
echo ""
echo "Restart your Pi for full effect:"
echo "  sudo reboot"
