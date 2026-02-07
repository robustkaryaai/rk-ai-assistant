#!/bin/bash
# Fix Bluetooth for PipeWire Config
set -e

echo "=== Fixing PipeWire Bluetooth Support ==="

echo "1. Installing Bluetooth modules for PipeWire..."
sudo apt update
sudo apt install -y libspa-0.2-bluetooth pipewire-audio-client-libraries wireplumber

echo "2. Restarting PipeWire services..."
systemctl --user restart wireplumber pipewire pipewire-pulse

echo "3. Waiting for services..."
sleep 5

echo "4. Checking Sinks..."
pactl list sinks short

echo "=== Fix Complete ==="
echo "Please restart rk-assistant: sudo systemctl restart rk-assistant.service"
