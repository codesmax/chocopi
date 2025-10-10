"""Configuration loading and constants"""
import os
import platform
import logging
import yaml
from pathlib import Path
from dotenv import load_dotenv

# Environment
IS_PI = platform.machine().lower() in ['aarch64', 'armv7l']
IS_MACOS = platform.system() == 'Darwin'
LOG_LEVEL = os.environ.get('CHOCO_LOG', 'INFO').upper()
USE_DISPLAY = bool(os.environ.get('CHOCO_DISPLAY', False))

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
