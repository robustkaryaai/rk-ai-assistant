#!/bin/bash
# Startup script for RK AI Assistant
# This script should be located in ~/Documents/rk-ai-assistant/start_rk.sh

# Navigate to Documents
cd ~/Documents

# Activate virtual environment
# Assuming rk-ai is the venv folder name
source rk-ai/bin/activate

# Navigate to project directory
cd rk-ai-assistant

# Update from git
echo "[startup] Checking for updates..."
git pull origin main

# Start the assistant
echo "[startup] Starting RK AI Assistant..."
python3 -m rk_assistant.main
