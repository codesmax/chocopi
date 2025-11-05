![Image of a friendly robot with a chocolatey treat for a head](https://github.com/user-attachments/assets/d197fcb5-cfa9-4faf-a3ce-9e9b94eb9ee0)

# ChocoPi

Smart speaker app for language education through conversation.
Built with a focus on simplicity, privacy, and configurability.

## Features

- English, Korean, Spanish and Chinese language support
- Wake word detection on device
- Voice conversation using OpenAI Realtime API
- Built for Raspberry Pi; some support for other platforms

## Quick Start

### Requirements
- Microphone and speaker
- OpenAI API key
- Python 3.11

### Raspberry Pi Automated Setup

**Tested on Raspberry Pi 4+ with 64-bit Raspberry Pi OS Lite (Trixie and Bookworm)**

1. Flash Raspberry Pi OS Lite (64-bit) with [rpi-imager](https://rpi.org/imager) (configure user, SSH, WiFi)
2. SSH into your Pi and run:

   **One-liner:**
   ```bash
   bash <(curl -fsSL https://raw.githubusercontent.com/codesmax/chocopi/main/install.sh)
   ```

   **Or clone first:**
   ```bash
   git clone https://github.com/codesmax/chocopi.git
   cd chocopi
   ./install.sh
   ```

### Linux/Mac/Windows Manual Setup

```bash
git clone https://github.com/codesmax/chocopi.git
cd chocopi

# Install uv if needed
pipx install uv

# Set up venv with Python 3.11 and install dependencies
uv venv .venv --python 3.11
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
uv pip install -e .

# Update .env file with your OpenAI API key
./chocopi
```

## Configuration

### Basic Configuration
- Add a `.env` with your OpenAI API key
- Update `config.yml` to customize user, language, wake word, and API settings

### Bluetooth Audio (Optional)

For Bluetooth microphone and speaker support:

**Pair your device**
   ```bash
   # Set device in pairing mode and connect
   sudo -u chocopi bluetoothctl
   scan on
   pair <MAC_ADDRESS>
   trust <MAC_ADDRESS>
   connect <MAC_ADDRESS>
   exit

   # Restart Wireplumber
   sudo -u chocopi XDG_RUNTIME_DIR=/var/run/user/$(id -u chocopi) systemctl --user restart wireplumber

   # Restart ChocoPi
   sudo systemctl restart chocopi
   ```

## Service Management

```bash
sudo systemctl start chocopi    # Start
sudo systemctl stop chocopi     # Stop
sudo systemctl status chocopi   # Check status
sudo journalctl -u chocopi -f   # View logs
```

## License

MIT
