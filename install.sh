#!/bin/bash
set -e

echo "Installing Choco Voice Assistant..."

# Platform checks
if [[ ! -f /etc/debian_version ]]; then
    echo "Error: This installer requires a Debian-based Linux distribution"
    exit 1
fi

# Check if running on Raspberry Pi and warn if not aarch64
if [[ -f /proc/cpuinfo ]] && grep -q "Raspberry Pi" /proc/cpuinfo; then
    ARCH=$(uname -m)
    if [[ "$ARCH" != "aarch64" ]]; then
        echo "Warning: You're running on a Raspberry Pi with $ARCH architecture."
        echo "For best performance, use a 64-bit Raspberry Pi OS (aarch64)."
        echo "Continuing in 5 seconds... (Ctrl+C to cancel)"
        sleep 5
    fi
fi

# Show installation summary and confirm
echo
echo "This script will:"
echo "  • Install system dependencies (pipewire, python3, etc.)"
echo "  • Create 'chocopi' user with limited privileges"
echo "  • Clone/update ChocoPi to /opt/chocopi"
echo "  • Set up Python virtual environment and dependencies"
echo "  • Configure PipeWire/WirePlumber for Bluetooth audio"
echo "  • Install and enable systemd service"
echo
read -p "Continue with installation? [Y/n] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]] && [[ -n $REPLY ]]; then
    echo "Installation cancelled."
    exit 0
fi

# Install system dependencies
echo "Installing system dependencies..."
sudo apt update
sudo apt install -y git pipx libportaudio2 libasound2-dev libegl1 libegl-dev pipewire pipewire-audio pulseaudio-utils

# Create chocopi user if it doesn't exist
if ! id "chocopi" &>/dev/null; then
    echo "Creating chocopi user..."
    sudo useradd -m -s /bin/bash -G audio,video,render,bluetooth chocopi

    # Enable linger to allow user services without login
    echo "Enabling systemd linger for chocopi user..."
    sudo loginctl enable-linger chocopi
fi

# Create application directory
if [[ ! -d /opt/chocopi ]]; then
    echo "Setting up application directory..."
    sudo mkdir -p /opt/chocopi
    sudo chown chocopi:chocopi /opt/chocopi
fi

# Clone repository if not already present
if [[ ! -d /opt/chocopi/.git ]]; then
    echo "Cloning Choco repository..."
    sudo -u chocopi git clone https://github.com/codesmax/chocopi.git /opt/chocopi
else
    echo "Repository already exists, updating..."
    sudo -u chocopi git -C /opt/chocopi pull
fi

# Install uv for chocopi user
echo "Installing uv for chocopi user..."
sudo -u chocopi pipx install uv
sudo -u chocopi pipx ensurepath

# Create virtual environment with Python 3.11 and install dependencies
echo "Setting up Python 3.11 environment with uv..."
cd /opt/chocopi
sudo -u chocopi /home/chocopi/.local/bin/uv venv .venv --python 3.11
sudo -u chocopi /home/chocopi/.local/bin/uv pip install -e . --python .venv/bin/python

# Make chocopi script executable
sudo chmod +x /opt/chocopi/chocopi

# Configure PipeWire/WirePlumber for Bluetooth audio
echo "Configuring PipeWire for Bluetooth audio..."
sudo -u chocopi mkdir -p /home/chocopi/.config/wireplumber/wireplumber.conf.d/
sudo -u chocopi cp /opt/chocopi/install/wireplumber/51-bluetooth-audio.conf \
    /home/chocopi/.config/wireplumber/wireplumber.conf.d/

# Enable and start PipeWire services for chocopi user
echo "Enabling PipeWire services for chocopi user..."
CHOCOPI_UID=$(id -u chocopi)
sudo -u chocopi XDG_RUNTIME_DIR=/run/user/$CHOCOPI_UID systemctl --user enable pipewire pipewire-pulse wireplumber
sudo -u chocopi XDG_RUNTIME_DIR=/run/user/$CHOCOPI_UID systemctl --user start pipewire pipewire-pulse wireplumber

# Install systemd service
echo "Installing systemd service..."
sudo cp /opt/chocopi/install/systemd/chocopi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable chocopi

# Prompt for OpenAI API key
echo
echo "Configuration"
echo "============="
read -p "Enter your OpenAI API key (or press Enter to configure later): " API_KEY

if [[ -n "$API_KEY" ]]; then
    echo "Creating .env file..."
    echo "OPENAI_API_KEY=$API_KEY" | sudo tee /opt/chocopi/.env > /dev/null
    sudo chown chocopi:chocopi /opt/chocopi/.env
    sudo chmod 600 /opt/chocopi/.env

    echo
    echo "Installation and configuration complete!"
    echo "Starting Choco service..."
    sudo systemctl start chocopi

    echo
    echo "Service status:"
    sudo systemctl status chocopi --no-pager -l
else
    echo
    echo "Installation complete!"
    echo "To configure later, create /opt/chocopi/.env with:"
    echo "  echo 'OPENAI_API_KEY=your_key_here' | sudo tee /opt/chocopi/.env"
    echo "  sudo chown chocopi:chocopi /opt/chocopi/.env"
    echo "  sudo chmod 600 /opt/chocopi/.env"
    echo "Then start the service:"
    echo "  sudo systemctl start chocopi"
fi

echo
echo "Useful commands:"
echo "  sudo systemctl status chocopi   # Check status"
echo "  sudo journalctl -u chocopi -f   # View logs"
echo
echo "Note: See README.md for more detailed instructions including Bluetooth audio setup."
