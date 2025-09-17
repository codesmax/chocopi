# ChocoPi

![Image of a friendly robot with a chocolatey treat for a head](https://github.com/user-attachments/assets/ea0a8348-0699-4f51-98e1-105f1fd10e16)

Smart speaker app for language education through conversation.
Built with a focus on simplicity, privacy, and configurability.


## Features
- English, Spanish and Korean language support
- Wake word detection on device
- Voice conversation using OpenAI Realtime API
- Built with portability in mind


## Quick Start

### Requirements

- Raspberry Pi 4+
- Microphone and speaker
- OpenAI API key
- Python 3.10+

### Raspberry Pi Setup

1. Flash Raspberry Pi OS with [rpi-imager](https://rpi.org/imager) (configure SSH, WiFi, user)
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

### Development Setup

```bash
git clone https://github.com/codesmax/chocopi.git
cd chocopi
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
# Update .env file with your OpenAI API key
./chocopi
```

## Configuration
- Add a `.env` with your OpenAI API key
- Update `config.yml` to customize user, language, wake word, and API settings.


## Service Management

```bash
sudo systemctl start chocopi    # Start
sudo systemctl stop chocopi     # Stop
sudo systemctl status chocopi   # Check status
sudo journalctl -u chocopi -f   # View logs
```

## License

MIT
