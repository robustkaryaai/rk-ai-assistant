#!/bin/bash
# Simple runner - just like developer mode but runs main.py
# No systemd, no complexity

cd /home/raspberrypi/Documents/rk-ai-assistant
source /home/raspberrypi/Documents/rk-ai/bin/activate

echo "Starting RK Assistant (simple mode)..."
echo "Press Ctrl+C to stop"
echo ""

# Run main.py directly, filtering out noisy ALSA/Jack errors
python3 -m rk_assistant.main 2> >(grep -v "ALSA" | grep -v "jack" | grep -v "Cannot connect to server" >&2)
