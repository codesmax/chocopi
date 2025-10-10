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

# Install system dependencies
echo "Installing system dependencies..."
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv libportaudio2 libegl1 python3-pygame

# Create chocopi user if it doesn't exist
if ! id "chocopi" &>/dev/null; then
    echo "Creating chocopi user..."
    sudo useradd -m -s /bin/bash -G audio chocopi
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

# Create virtual environment and install Python dependencies
echo "Setting up Python environment..."
sudo -u chocopi python3 -m venv /opt/chocopi/.venv
sudo -u chocopi /opt/chocopi/.venv/bin/pip install -e /opt/chocopi

# Make chocopi script executable
sudo chmod +x /opt/chocopi/chocopi

# Install systemd service
echo "Installing systemd service..."
sudo cp /opt/chocopi/chocopi.service /etc/systemd/system/
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
