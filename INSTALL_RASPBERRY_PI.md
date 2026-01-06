# RK AI Assistant - Raspberry Pi Installation Guide

Complete installation guide for setting up the RK AI Assistant on Raspberry Pi Zero W.

## Prerequisites

- Raspberry Pi Zero W (or any Raspberry Pi with Bluetooth)
- Raspberry Pi OS (Bookworm or later)
- Internet connection
- Git installed

## Step 1: Install System Dependencies

```bash
# Update package list
sudo apt-get update

# Install audio and Bluetooth dependencies
sudo apt-get install -y \
    python3-pip \
    espeak \
    mpg123 \
    alsa-utils \
    bluez \
    bluez-tools \
    portaudio19-dev \
    python3-dev \
    libbluetooth-dev

# Install Python system packages (for dbus and GObject)
sudo apt-get install -y \
    python3-dbus \
    python3-gi \
    python3-gi-cairo

# Install PocketSphinx dependencies (for wake word detection)
sudo apt-get install -y \
    swig \
    libpulse-dev \
    libasound2-dev \
    libsphinxbase-dev \
    libpocketsphinx-dev
```

## Step 2: Clone Repository

```bash
# Navigate to your preferred directory
cd ~/Documents

# Clone the repository
git clone https://github.com/robustkaryaai/rk-ai-assistant.git

# Enter the directory
cd rk-ai-assistant
```

## Step 3: Create Virtual Environment

```bash
# Create virtual environment
python3 -m venv rk-ai-env

# Activate virtual environment
source rk-ai-env/bin/activate
```

## Step 4: Install Python Dependencies

```bash
# Install from requirements.txt
pip install -r requirements.txt

# Install PocketSphinx (optional but recommended for wake word)
pip install pocketsphinx
```

## Step 5: Configure the Application

### Create Configuration Files

1. **Create slug file**:
```bash
# Create a 9-digit slug (unique identifier for your device)
echo "123456789" > rk_assistant/slug.txt
```

2. **Create .env file**:
```bash
# Create .env file in the project root
nano .env
```

Add the following to `.env`:
```env
# Appwrite Configuration
APPWRITE_ENDPOINT=https://cloud.appwrite.io/v1
APPWRITE_PROJECT_ID=your_project_id_here
APPWRITE_API_KEY=your_api_key_here
APPWRITE_DB_ID=your_database_id_here
APPWRITE_USERS_COLLECTION=your_collection_id_here

# API Keys
WEATHER_API_KEY=your_weatherapi_key_here
NEWS_API_KEY=your_newsapi_key_here

# Optional: Bluetooth RFCOMM channel (default: 3)
BT_CHANNEL=3
```

3. **Secure the .env file**:
```bash
chmod 600 .env
```

## Step 6: Test the Installation

```bash
# Verify dbus and gi imports
python3 -c "import dbus; import gi; print('✅ System packages OK')"

# Test the application
python3 -m rk_assistant.main
```

## Step 7: Run as a Service (Optional)

To run the assistant automatically on boot:

1. **Create systemd service file**:
```bash
sudo nano /etc/systemd/system/rk-ai-assistant.service
```

2. **Add the following content**:
```ini
[Unit]
Description=RK AI Assistant
After=network.target bluetooth.target

[Service]
Type=simple
User=raspberrypi
WorkingDirectory=/home/raspberrypi/Documents/rk-ai-assistant
Environment="PATH=/home/raspberrypi/Documents/rk-ai-assistant/rk-ai-env/bin"
ExecStart=/home/raspberrypi/Documents/rk-ai-assistant/rk-ai-env/bin/python -m rk_assistant.main
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

3. **Enable and start the service**:
```bash
sudo systemctl daemon-reload
sudo systemctl enable rk-ai-assistant.service
sudo systemctl start rk-ai-assistant.service

# Check status
sudo systemctl status rk-ai-assistant.service
```

## Troubleshooting

### Issue: ModuleNotFoundError: No module named 'dbus'
**Solution**: Install system packages
```bash
sudo apt-get install -y python3-dbus python3-gi python3-gi-cairo
```

Do NOT try to install `dbus-python` or `PyGObject` via pip on Raspberry Pi - use the system packages instead.

### Issue: Audio not working
**Solution**: Check audio output
```bash
# List audio devices
aplay -l

# Test speaker
speaker-test -t wav -c 2

# Adjust volume
alsamixer
```

### Issue: Bluetooth not working
**Solution**: Ensure Bluetooth is enabled
```bash
sudo systemctl status bluetooth
sudo hciconfig hci0 up
```

## Updating the Code

To update to the latest version:

```bash
cd ~/Documents/rk-ai-assistant
git pull origin main
source rk-ai-env/bin/activate
pip install -r requirements.txt --upgrade
```

## Git Commands Reference

```bash
# Check status
git status

# Pull latest changes
git pull origin main

# Make changes and push
git add .
git commit -m "Your message"
git push origin main
```

## Notes

- The Bluetooth service will advertise as `rk-ai-{SLUG}` where SLUG is from `rk_assistant/slug.txt`
- Wake word is "rk" by default (requires PocketSphinx)
- Temporary audio files are stored in `rk_assistant/data/`
- Weather/news caches are stored in `rk_assistant/data/weather.json` and `rk_assistant/data/news.json`
