#!/bin/bash
# Install RK Assistant as a USER service (not system service)
# This gives it access to PipeWire/PulseAudio

set -e

echo "=== Installing RK Assistant as User Service ==="

# 1. Stop and disable system service if running
if systemctl is-active --quiet rk-assistant.service; then
    echo "[*] Stopping system service..."
    sudo systemctl stop rk-assistant.service
fi

if systemctl is-enabled --quiet rk-assistant.service 2>/dev/null; then
    echo "[*] Disabling system service..."
    sudo systemctl disable rk-assistant.service
fi

# 2. Create user service directory
mkdir -p ~/.config/systemd/user

# 3. Create user service file
cat > ~/.config/systemd/user/rk-assistant.service <<'EOF'
[Unit]
Description=RK AI Assistant (User Service)
After=pipewire.service

[Service]
Type=simple
WorkingDirectory=%h/Documents/rk-ai-assistant
ExecStart=/usr/bin/bash %h/Documents/rk-ai-assistant/start_rk.sh
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

echo "[*] User service file created"

# 4. Reload systemd user daemon
systemctl --user daemon-reload

# 5. Enable and start
systemctl --user enable rk-assistant.service
systemctl --user start rk-assistant.service

echo ""
echo "✅ Installation complete!"
echo ""
echo "Useful commands:"
echo "  systemctl --user status rk-assistant"
echo "  systemctl --user restart rk-assistant"
echo "  journalctl --user -u rk-assistant -f"
echo ""
