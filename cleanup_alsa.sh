#!/bin/bash
# Remove lingering ALSA/BlueALSA configs
sudo rm -f /etc/asound.conf
sudo rm -f /home/raspberrypi/.asoundrc
sudo rm -f /usr/share/alsa/alsa.conf.d/*bluealsa*
# Also remove any pulse cookie issues?
rm -f ~/.config/pulse/cookie
echo "ALSA cleanup complete."
