#!/bin/bash
# build_llama.sh — Builds llama.cpp from source on Raspberry Pi Zero W
# Run from: ~/Documents/rk-ai-assistant/v2/
# Usage: bash llm/build_llama.sh

set -e

LLAMA_DIR="$HOME/llama.cpp"
INSTALL_BIN="$HOME/.local/bin/llama-cli"

echo "=================================================="
echo "  🔨 Building llama.cpp for Raspberry Pi Zero W"
echo "  ⚠️  This will take 20-60 minutes. Go have chai."
echo "=================================================="

# 1. Dependencies
echo ""
echo "📦 Installing build dependencies..."
sudo apt update -qq
sudo apt install -y git cmake make g++ libopenblas-dev 2>/dev/null || \
sudo apt install -y git cmake make g++ 2>/dev/null

# 2. Clone
# 2. Clone or update to stable release (b3900 is proven stable with llama-cli)
STABLE_TAG="b3900"
if [ -d "$LLAMA_DIR" ]; then
    echo "📁 llama.cpp already cloned, checking out stable tag $STABLE_TAG..."
    cd "$LLAMA_DIR"
    git fetch --tags --depth=1 origin tag "$STABLE_TAG" 2>/dev/null || git fetch --tags origin
    git checkout -f "$STABLE_TAG"
else
    echo "📥 Cloning llama.cpp ($STABLE_TAG)..."
    git clone --depth=1 --branch "$STABLE_TAG" https://github.com/ggerganov/llama.cpp "$LLAMA_DIR"
fi

# 3. Build — single thread on Pi Zero W (single core)
echo ""
echo "🔨 Building... (single thread, -j1 for Pi Zero W stability)"
cd "$LLAMA_DIR"
rm -rf build && mkdir -p build && cd build
cmake .. \
    -DLLAMA_BUILD_SERVER=OFF \
    -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_EXAMPLES=ON \
    -DCMAKE_BUILD_TYPE=Release \
    -DGGML_OPENBLAS=ON 2>/dev/null || \
cmake .. \
    -DLLAMA_BUILD_SERVER=OFF \
    -DLLAMA_BUILD_TESTS=OFF \
    -DLLAMA_BUILD_EXAMPLES=ON \
    -DCMAKE_BUILD_TYPE=Release

cmake --build . --config Release --target llama-cli -j1

# 4. Install to ~/.local/bin
echo ""
mkdir -p "$HOME/.local/bin"
if [ -f "$LLAMA_DIR/build/bin/llama-cli" ]; then
    cp "$LLAMA_DIR/build/bin/llama-cli" "$INSTALL_BIN"
    chmod +x "$INSTALL_BIN"
    echo "✅ Installed to $INSTALL_BIN"
elif [ -f "$LLAMA_DIR/build/llama-cli" ]; then
    cp "$LLAMA_DIR/build/llama-cli" "$INSTALL_BIN"
    chmod +x "$INSTALL_BIN"
    echo "✅ Installed to $INSTALL_BIN"
else
    # Fallback: search
    BUILT=$(find "$LLAMA_DIR/build" -name "llama-cli" -type f 2>/dev/null | head -1)
    if [ -n "$BUILT" ]; then
        cp "$BUILT" "$INSTALL_BIN"
        chmod +x "$INSTALL_BIN"
        echo "✅ Installed to $INSTALL_BIN"
    else
        echo "❌ Build failed — llama-cli binary not found."
        exit 1
    fi
fi

# 5. Add to PATH if not already there
if ! grep -q ".local/bin" "$HOME/.bashrc"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
fi
export PATH="$HOME/.local/bin:$PATH"

echo ""
echo "=================================================="
echo "  ✅ llama.cpp built and ready!"
echo "  Binary: $INSTALL_BIN"
echo ""
echo "  Next step:"
echo "    python3 llm/download_model.py"
echo "=================================================="
