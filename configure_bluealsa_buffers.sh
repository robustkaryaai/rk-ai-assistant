#!/bin/bash
# Configure bluealsa-aplay with larger buffers
# This should eliminate audio crackling/cutting

set -e

echo "======================================"
echo "Configuring bluealsa-aplay buffers"
echo "======================================"
echo ""

SPEAKER_MAC="D0:78:1D:4F:F4:1E"

echo "1. Stopping existing bluealsa-aplay..."
sudo systemctl stop bluealsa-aplay 2>/dev/null || sudo pkill bluealsa-aplay 2>/dev/null || true
sleep 1

echo "2. Starting bluealsa-aplay with large buffers..."
# --pcm-buffer-time: 500000 = 500ms buffer
# --pcm-period-time: 100000 = 100ms period
sudo bluealsa-aplay --pcm-buffer-time=500000 --pcm-period-time=100000 $SPEAKER_MAC &

sleep 2

echo ""
echo "======================================"
echo "✓ bluealsa-aplay configured!"
echo "======================================"
echo ""
echo "Buffer settings:"
echo "  - Buffer time: 500ms"
echo "  - Period time: 100ms"
echo ""
echo "Test audio output and check for crackling."
