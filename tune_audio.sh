#!/bin/bash
# Tune PulseAudio for High Gain (Distant Mic)
echo "=== Tuning Audio for Distance ==="

# 1. Unmute everything
echo "Unmuting..."
pactl set-sink-mute @DEFAULT_SINK@ 0
pactl set-source-mute @DEFAULT_SOURCE@ 0

# 2. Boost volume to 150% (software amplification)
# Note: PipeWire allows >100% volume
echo "Boosting Mic Volume to 150%..."
pactl set-source-volume @DEFAULT_SOURCE@ 150%

# 3. Check current volume
echo "Current Volume:"
pactl get-source-volume @DEFAULT_SOURCE@

echo "=== Tuning Complete ==="
