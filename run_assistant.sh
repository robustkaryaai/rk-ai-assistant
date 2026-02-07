#!/bin/bash
# Simple runner - just like developer mode but runs main.py
# No systemd, no complexity

cd /home/raspberrypi/Documents/rk-ai-assistant
source /home/raspberrypi/Documents/rk-ai/bin/activate

# Silence ALSA backend scanning noise
export ALSA_CARD=default

echo "Starting RK Assistant (simple mode)..."
echo "Press Ctrl+C to stop"
echo ""

# Run main.py directly
python3 -m rk_assistant.main
