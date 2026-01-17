#!/bin/bash
# Bluetooth Hardware Diagnostic Script
# Run this to identify Bluetooth adapter issues

echo "======================================"
echo "Bluetooth Hardware Diagnostic"
echo "======================================"
echo ""

echo "1. USB Devices:"
echo "--------------------------------------"
lsusb
echo ""

echo "2. All Bluetooth HCI Interfaces:"
echo "--------------------------------------"
sudo hciconfig -a
echo ""

echo "3. Bluetooth Controllers (bluetoothctl):"
echo "--------------------------------------"
bluetoothctl list
echo ""

echo "4. Bluetooth Service Status:"
echo "--------------------------------------"
systemctl status bluetooth --no-pager
echo ""

echo "5. Recent Bluetooth Kernel Messages:"
echo "--------------------------------------"
dmesg | grep -i bluetooth | tail -30
echo ""

echo "6. BlueZ Version:"
echo "--------------------------------------"
bluetoothctl --version
echo ""

echo "======================================"
echo "Diagnostic Complete"
echo "======================================"
echo ""
echo "Please share this output to diagnose the Bluetooth issue."
