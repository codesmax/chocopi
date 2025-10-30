#!/bin/bash
set -e

# ============================================================================
# Configuration - customize if desired
# ============================================================================
CHOCOPI_USER="${CHOCOPI_USER:-chocopi}"
CHOCOPI_HOME="/home/${CHOCOPI_USER}"
CHOCOPI_INSTALL_DIR="${CHOCOPI_INSTALL_DIR:-/opt/chocopi}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"
GITHUB_REPO="${GITHUB_REPO:-https://github.com/codesmax/chocopi.git}"

# ============================================================================
# Output formatting
# ============================================================================
BOLD='\033[1m'
RESET='\033[0m'

info() { echo -e "${BOLD}[⚙️]${RESET} ${BOLD}$1${RESET}"; }
success() { echo -e "${BOLD}[✨]${RESET} $1\n"; }
warn() { echo -e "${BOLD}[⚠️]${RESET} $1"; }
error() { echo -e "${BOLD}[❌]${RESET} $1" >&2; }

# ============================================================================
# Installation
# ============================================================================
info "Installing ChocoPi Language Tutor..."

# Platform checks
if [[ ! -f /etc/debian_version ]]; then
    error "Error: This installer requires a Debian-based Linux distribution"
    exit 1
fi

# Check if running on Raspberry Pi and warn if not aarch64
if [[ -f /proc/cpuinfo ]] && grep -q "Raspberry Pi" /proc/cpuinfo; then
    ARCH=$(uname -m)
    if [[ "$ARCH" != "aarch64" ]]; then
        warn "Warning: Running on Raspberry Pi with $ARCH architecture"
        warn "For best performance, use a 64-bit Raspberry Pi OS (aarch64)"
        warn "Continuing in 5 seconds... (Ctrl+C to cancel)"
        sleep 5
    fi
fi

# Show installation summary and confirm
echo
echo "This script will:"
echo "  • Install system dependencies (pipewire, python3, etc.)"
echo "  • Create '${CHOCOPI_USER}' user with limited privileges"
echo "  • Clone/update ChocoPi to ${CHOCOPI_INSTALL_DIR}"
echo "  • Set up Python ${PYTHON_VERSION} virtual environment and dependencies"
echo "  • Optionally configure PipeWire/WirePlumber for Bluetooth audio"
echo "  • Install and enable systemd service"
echo
read -p "Continue with installation? [Y/n] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]] && [[ -n $REPLY ]]; then
    info "Installation cancelled"
    exit 0
fi

# Install system dependencies
info "Installing system dependencies..."
sudo apt update
sudo apt install -y git pipx libportaudio2 libasound2-dev libegl1 libegl-dev pipewire pipewire-audio pulseaudio-utils
success "System dependencies installed"

# Create chocopi user if it doesn't exist
if ! id "${CHOCOPI_USER}" &>/dev/null; then
    info "Creating ${CHOCOPI_USER} user..."
    sudo useradd -m -s /bin/bash -G audio,video,render,bluetooth "${CHOCOPI_USER}"
    success "User ${CHOCOPI_USER} created"

    # Enable linger to allow user services without login
    info "Enabling systemd linger for ${CHOCOPI_USER} user..."
    sudo loginctl enable-linger "${CHOCOPI_USER}"
    success "Systemd linger enabled"
fi

# Create application directory
if [[ ! -d "${CHOCOPI_INSTALL_DIR}" ]]; then
    info "Setting up application directory..."
    sudo mkdir -p "${CHOCOPI_INSTALL_DIR}"
    sudo chown "${CHOCOPI_USER}:${CHOCOPI_USER}" "${CHOCOPI_INSTALL_DIR}"
    success "Application directory created at ${CHOCOPI_INSTALL_DIR}"
fi

# Clone repository if not already present
if [[ ! -d "${CHOCOPI_INSTALL_DIR}/.git" ]]; then
    info "Cloning ChocoPi repository..."
    sudo -u "${CHOCOPI_USER}" git clone "${GITHUB_REPO}" "${CHOCOPI_INSTALL_DIR}"
    success "Repository cloned"
else
    info "Repository already exists, updating..."
    sudo -u "${CHOCOPI_USER}" git -C "${CHOCOPI_INSTALL_DIR}" pull
    success "Repository updated"
fi

# Install uv for chocopi user
info "Installing uv for ${CHOCOPI_USER} user..."
sudo -u "${CHOCOPI_USER}" pipx install uv
sudo -u "${CHOCOPI_USER}" pipx ensurepath
success "uv installed"

# Create virtual environment with Python and install dependencies
info "Setting up Python ${PYTHON_VERSION} environment with uv..."
cd "${CHOCOPI_INSTALL_DIR}"
sudo -u "${CHOCOPI_USER}" "${CHOCOPI_HOME}/.local/bin/uv" venv .venv --python "${PYTHON_VERSION}"
sudo -u "${CHOCOPI_USER}" "${CHOCOPI_HOME}/.local/bin/uv" pip install -e . --python .venv/bin/python
success "Python environment configured"

# Make chocopi script executable
sudo chmod +x "${CHOCOPI_INSTALL_DIR}/chocopi"

# Configure PipeWire/WirePlumber for Bluetooth audio
info "Configuring PipeWire/WirePlumber for Bluetooth audio..."

# Detect WirePlumber version to determine config format
WP_VERSION=$(dpkg-query -W -f='${Version}' wireplumber 2>/dev/null | grep -oP '^\d+\.\d+' || echo "0.5")
WP_MAJOR=$(echo "$WP_VERSION" | cut -d. -f1)
WP_MINOR=$(echo "$WP_VERSION" | cut -d. -f2)

if [[ "$WP_MAJOR" -eq 0 ]] && [[ "$WP_MINOR" -lt 5 ]]; then
    # WirePlumber 0.4.x uses Lua format
    info "Detected WirePlumber ${WP_VERSION} (using Lua config format)"
    WP_CONFIG_DIR="${CHOCOPI_HOME}/.config/wireplumber/bluetooth.lua.d"
    WP_CONFIG_FILE="51-bluetooth-audio.lua"
else
    # WirePlumber 0.5.x+ uses conf format
    info "Detected WirePlumber ${WP_VERSION} (using conf format)"
    WP_CONFIG_DIR="${CHOCOPI_HOME}/.config/wireplumber/wireplumber.conf.d"
    WP_CONFIG_FILE="51-bluetooth-audio.conf"
fi

# Install appropriate WirePlumber config file
if [[ -f "${CHOCOPI_INSTALL_DIR}/install/wireplumber/${WP_CONFIG_FILE}" ]]; then
    sudo -u "${CHOCOPI_USER}" mkdir -p "${WP_CONFIG_DIR}"
    sudo -u "${CHOCOPI_USER}" cp "${CHOCOPI_INSTALL_DIR}/install/wireplumber/${WP_CONFIG_FILE}" \
        "${WP_CONFIG_DIR}/"
    success "WirePlumber Bluetooth config installed"
fi

# Enable and start PipeWire services for chocopi user
info "Enabling PipeWire services for ${CHOCOPI_USER} user..."
CHOCOPI_UID=$(id -u "${CHOCOPI_USER}")
sudo -u "${CHOCOPI_USER}" XDG_RUNTIME_DIR=/run/user/$CHOCOPI_UID systemctl --user enable pipewire pipewire-pulse wireplumber
sudo -u "${CHOCOPI_USER}" XDG_RUNTIME_DIR=/run/user/$CHOCOPI_UID systemctl --user start pipewire pipewire-pulse wireplumber
success "PipeWire services enabled and started"

# Install systemd service
info "Installing systemd service..."
sudo cp "${CHOCOPI_INSTALL_DIR}/install/systemd/chocopi.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable chocopi
success "Systemd service installed and enabled"

# Prompt for OpenAI API key
info "Configuring OpenAI API..."
read -p "Enter your OpenAI API key (or press Enter to configure later): " API_KEY

if [[ -n "$API_KEY" ]]; then
    info "Creating .env file..."
    echo "OPENAI_API_KEY=$API_KEY" | sudo tee "${CHOCOPI_INSTALL_DIR}/.env" > /dev/null
    sudo chown "${CHOCOPI_USER}:${CHOCOPI_USER}" "${CHOCOPI_INSTALL_DIR}/.env"
    sudo chmod 600 "${CHOCOPI_INSTALL_DIR}/.env"
    success ".env file created"

    success "Installation and configuration complete!"
    info "Starting ChocoPi service..."
    sudo systemctl start chocopi

    echo
    info "Service status:"
    sudo systemctl status chocopi --no-pager -l
else
    success "Installation complete!"
    info "To configure later, create ${CHOCOPI_INSTALL_DIR}/.env with:"
    echo "  echo 'OPENAI_API_KEY=your_key_here' | sudo tee ${CHOCOPI_INSTALL_DIR}/.env"
    echo "  sudo chown ${CHOCOPI_USER}:${CHOCOPI_USER} ${CHOCOPI_INSTALL_DIR}/.env"
    echo "  sudo chmod 600 ${CHOCOPI_INSTALL_DIR}/.env"
    echo
    info "Then start the service:"
    echo "  sudo systemctl start chocopi"
fi

echo
info "Useful commands:"
echo "  sudo systemctl status chocopi   # Check status"
echo "  sudo journalctl -u chocopi -f   # View logs"
echo
info "To pair a Bluetooth audio device:"
echo "  bluetoothctl"
echo "  scan on"
echo "  pair <MAC_ADDRESS>"
echo "  trust <MAC_ADDRESS>"
echo "  connect <MAC_ADDRESS>"
echo "  exit"
echo
info "See README.md for more detailed setup and configuration instructions."
