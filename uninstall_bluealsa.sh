#!/bin/bash
# Uninstall BlueALSA to fix PyAudio scanning hangs
echo "=== Removing BlueALSA ==="
sudo apt remove -y bluez-alsa-utils libasound2-plugin-bluez
sudo apt autoremove -y

echo "=== Cleaning leftover configs ==="
sudo rm -f /etc/asound.conf
sudo rm -f /home/raspberrypi/.asoundrc
sudo rm -f /usr/share/alsa/alsa.conf.d/*bluealsa*

echo "Done. Please restart: ./start_rk.sh"
