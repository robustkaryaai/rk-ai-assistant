#!/bin/bash
# Aggressive cleanup of BlueALSA configs to fix PyAudio hang
echo "=== NUKING BlueALSA Configs ==="

# 1. Purge packages (removes configs usually)
sudo apt purge -y bluez-alsa-utils libasound2-plugin-bluez

# 2. Find and destroy ALL config files containing "bluealsa" in filename
echo "Searching /usr/share/alsa..."
sudo find /usr/share/alsa -type f -name "*bluealsa*" -exec rm -v {} \;

echo "Searching /etc/alsa..."
sudo find /etc/alsa -type f -name "*bluealsa*" -exec rm -v {} \;

echo "Searching /etc/asound.conf..."
sudo rm -vf /etc/asound.conf

echo "Searching ~/.asoundrc..."
rm -vf /home/raspberrypi/.asoundrc

# 3. Reload ALSA (just in case)
sudo alsa force-reload

echo "=== NUKE COMPLETE. Please restart app. ==="
