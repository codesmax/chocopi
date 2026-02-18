![Image of a friendly robot with a chocolatey treat for a head](https://github.com/user-attachments/assets/d197fcb5-cfa9-4faf-a3ce-9e9b94eb9ee0)

# ChocoPi

A voice-powered language tutor for kids, built for Raspberry Pi.

ChocoPi listens for a wake word, then holds a live conversation to help children practice English, Korean, Spanish, or Chinese. Each language has its own wake word, sleep word, and teaching style — all configurable.

## Demo
<video controls width="600">
  <source src="https://github.com/codesmax/chocopi/releases/download/demo-video/chocopi-demo.mp4" type="video/mp4">
</video>

## How It Works

1. Wake word detection runs on-device using [OpenWakeWord](https://github.com/dscripka/openWakeWord)
2. Once triggered, a voice conversation starts via the [OpenAI Realtime API](https://platform.openai.com/docs/guides/realtime)
3. The assistant adapts to the child's age, native language, and comprehension level
4. Sessions end with a language-specific sleep word or timeout
5. Conversation history is summarized and persisted for continuity across sessions

## Features

- **4 languages** — English, Korean, Spanish, and Chinese
- **On-device wake words** — "Hey Choco", "Anyeong Choco", "Hola Choco", "Nihao Choco"
- **User profiles** — per-child age, native language, and learning levels
- **Session memory** — remembers jokes, vocab, topics, and progress across conversations
- **Optional display** — animated character and live transcript panel (pygame-ce)
- **Runs headless** — no screen required; works as a systemd service on Pi

## Quick Start

### Requirements

- Microphone and speaker (Bluetooth or wired)
- OpenAI API key
- Python 3.11

### Raspberry Pi Setup

Tested on Raspberry Pi 4+ with 64-bit Raspberry Pi OS Lite (Trixie and Bookworm).

1. Flash Raspberry Pi OS Lite (64-bit) with [rpi-imager](https://rpi.org/imager) (configure user, SSH, WiFi)
2. SSH into your Pi and run:

   ```bash
   bash <(curl -fsSL https://raw.githubusercontent.com/codesmax/chocopi/main/install.sh)
   ```

   Or clone first:
   ```bash
   git clone https://github.com/codesmax/chocopi.git
   cd chocopi
   ./install.sh
   ```

   The installer handles system dependencies, audio stack setup, Python environment, and systemd service creation.

### Manual Setup (Linux / macOS / Windows)

```bash
git clone https://github.com/codesmax/chocopi.git
cd chocopi

# Install uv if needed
pipx install uv

# Create venv with Python 3.11 and install
uv venv .venv --python 3.11
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
uv pip install -e .

# Configure
cp .env.example .env       # add your OPENAI_API_KEY
nano config.yml            # set active_profile, languages, etc.

# Run
./chocopi
```

## Configuration

All settings live in two files:

| File | Contents |
|---|---|
| `.env` | `OPENAI_API_KEY` |
| `config.yml` | Profiles, languages, wake/sleep words, prompts, audio settings, display settings, OpenAI model config |

### Profiles

Profiles let multiple users share one device. Each profile specifies age, native language, and learning languages with comprehension levels. Set `active_profile` in `config.yml` to switch.

### Bluetooth Audio

For Bluetooth microphone and speaker support:

```bash
# Pair your device
sudo -u chocopi bluetoothctl
scan on
pair <MAC_ADDRESS>
trust <MAC_ADDRESS>
connect <MAC_ADDRESS>
exit

# Restart WirePlumber and ChocoPi
sudo -u chocopi XDG_RUNTIME_DIR=/var/run/user/$(id -u chocopi) systemctl --user restart wireplumber
sudo systemctl restart chocopi
```

## Service Management

```bash
sudo systemctl start chocopi    # Start
sudo systemctl stop chocopi     # Stop
sudo systemctl status chocopi   # Check status
sudo journalctl -u chocopi -f   # View logs
```

## Project Structure

```
chocopi                     # Bash entry point
src/chocopi/                # Python package
  chocopi.py                #   Main orchestrator
  wakeword.py               #   Wake word detection
  conversation.py           #   OpenAI Realtime API session
  audio.py                  #   Audio I/O
  display.py                #   Optional pygame-ce UI
  memory.py                 #   Session memory persistence
  language.py               #   Language detection
  config.py                 #   Config and env loading
config.yml                  # Runtime configuration
models/                     # Wake word models (.tflite + .onnx)
assets/                     # Sounds, images, fonts
install/                    # Systemd service + WirePlumber configs
data/                       # Per-profile memory files (gitignored)
```

## License

MIT
