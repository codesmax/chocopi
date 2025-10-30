"""Configuration loading and constants"""
import os
import platform
import logging
import yaml
from pathlib import Path
from dotenv import load_dotenv

def _has_display():
    """Check if a display is available"""
    system = platform.system()

    if system == 'Linux':
        # Check for X11, Wayland, or framebuffer
        return bool(
            os.environ.get('DISPLAY') or
            os.environ.get('WAYLAND_DISPLAY') or
            os.path.exists('/dev/fb0')
        )
    elif system in ('Darwin', 'Windows'):
        return True

    return False

# Environment
IS_PI = platform.machine().lower() in ['aarch64', 'armv7l']
LOG_LEVEL = os.environ.get('CHOCO_LOG', 'INFO').upper()
USE_DISPLAY = os.environ.get('CHOCO_DISPLAY') == '1' and _has_display()

# Configure logging
logging.basicConfig(level=logging.WARNING)  # Silence third-party libraries
logging.getLogger('chocopi').setLevel(getattr(logging, LOG_LEVEL))

# Project root (../..)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_PATH = PROJECT_ROOT / 'models'
ASSETS_PATH = PROJECT_ROOT / 'assets'
SOUNDS_PATH = ASSETS_PATH / 'sounds'
IMAGES_PATH = ASSETS_PATH / 'images'
FONTS_PATH = ASSETS_PATH / 'fonts'

# Load configuration
with open(PROJECT_ROOT / 'config.yml', 'r', encoding='utf-8') as file:
    CONFIG = yaml.safe_load(file)

# Load environment variables
load_dotenv(PROJECT_ROOT / '.env')
