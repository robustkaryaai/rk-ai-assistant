#!/bin/bash
echo "=== PulseAudio Diagnosis ==="
echo "1. PulseAudio Status:"
pulseaudio --check && echo "Running" || echo "Not Running"
echo ""

echo "2. PA Info:"
pactl info 2>/dev/null || echo "Failed to get info"
echo ""

echo "3. Sinks:"
pactl list sinks short 2>/dev/null || echo "Failed to list sinks"
echo ""

echo "4. Default Sink:"
pactl get-default-sink 2>/dev/null || echo "Failed to get default sink"
echo ""

echo "5. Bluetooth Devices:"
bluetoothctl devices
echo ""

echo "6. Bluetooth Info (if any connected):"
# Extract MAC of first connected device if any
MAC=$(bluetoothctl devices | head -n 1 | awk '{print $2}')
if [ ! -z "$MAC" ]; then
    bluetoothctl info "$MAC"
fi
echo ""

echo "7. ALSA Output Devices:"
aplay -L | grep -iE "pulse|blue"
echo ""

echo "=== End Diagnosis ==="
