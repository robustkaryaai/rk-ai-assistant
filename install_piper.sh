#!/bin/bash
# Piper TTS Installation Script for Raspberry Pi
# This script installs Piper TTS and downloads a high-quality voice model

set -e  # Exit on error

echo "=================================="
echo "Installing Piper TTS"
echo "=================================="

# Detect architecture
ARCH=$(uname -m)
echo "Detected architecture: $ARCH"

# Determine download URL based on architecture
if [[ "$ARCH" == "aarch64" ]] || [[ "$ARCH" == "arm64" ]]; then
    PIPER_URL="https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_arm64.tar.gz"
elif [[ "$ARCH" == "armv7l" ]] || [[ "$ARCH" == "armhf" ]]; then
    PIPER_URL="https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_armv7l.tar.gz"
else
    echo "❌ Unsupported architecture: $ARCH"
    echo "Piper TTS requires ARM64 or ARMv7l"
    exit 1
fi

# Create temp directory
TMP_DIR=$(mktemp -d)
cd "$TMP_DIR"

echo ""
echo "📥 Downloading Piper TTS..."
wget -q --show-progress "$PIPER_URL" -O piper.tar.gz

echo ""
echo "📦 Extracting..."
tar xzf piper.tar.gz

echo ""
echo "📝 Installing to /usr/local/bin/piper..."
sudo cp piper/piper /usr/local/bin/piper
sudo chmod +x /usr/local/bin/piper

# Clean up temp files
cd ~
rm -rf "$TMP_DIR"

echo ""
echo "=================================="
echo "Downloading Voice Model"
echo "=================================="

# Create voice model directory
VOICE_DIR="$HOME/.local/share/piper/voices"
mkdir -p "$VOICE_DIR"

cd "$VOICE_DIR"

echo ""
echo "📥 Downloading en_US-lessac-medium voice model..."
echo "This is a high-quality female voice (~25MB)"

# Download voice model and config
wget -q --show-progress \
    "https://github.com/rhasspy/piper/releases/download/v1.2.0/en_US-lessac-medium.onnx" \
    -O en_US-lessac-medium.onnx

wget -q --show-progress \
    "https://github.com/rhasspy/piper/releases/download/v1.2.0/en_US-lessac-medium.onnx.json" \
    -O en_US-lessac-medium.onnx.json

echo ""
echo "✅ Installation complete!"
echo ""
echo "=================================="
echo "Testing Piper TTS"
echo "=================================="

# Test Piper
echo "Testing voice output..."
echo "Hello! Piper TTS is now installed." | /usr/local/bin/piper --model "$VOICE_DIR/en_US-lessac-medium.onnx" --output_file - | mpg123 -q - 2>/dev/null || {
    echo "⚠️  Test playback failed, but Piper is installed."
    echo "Make sure mpg123 is installed: sudo apt-get install mpg123"
}

echo ""
echo "=================================="
echo "Installation Summary"
echo "=================================="
echo "✅ Piper executable: /usr/local/bin/piper"
echo "✅ Voice model: $VOICE_DIR/en_US-lessac-medium.onnx"
echo ""
echo "You can now restart your RK Assistant to use Piper TTS!"
echo "Run: python -m rk_assistant.main"
echo "=================================="
