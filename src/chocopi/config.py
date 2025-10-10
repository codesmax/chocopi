"""Configuration loading and constants"""
import os
import platform
import yaml
from dotenv import load_dotenv

# Environment
DEBUG = bool(os.environ.get('DEBUG'))
IS_PI = platform.machine().lower() in ['aarch64', 'armv7l']
IS_MACOS = platform.system() == 'Darwin'

# Project root is two directories up from this file (src/chocopi/config.py)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
MODELS_PATH = os.path.join(PROJECT_ROOT, 'models')
SOUNDS_PATH = os.path.join(PROJECT_ROOT, 'assets', 'sounds')
IMAGES_PATH = os.path.join(PROJECT_ROOT, 'assets', 'images')
FONTS_PATH = os.path.join(PROJECT_ROOT, 'assets', 'fonts')

# Load configuration
with open(os.path.join(PROJECT_ROOT, 'config.yml'), 'r', encoding='utf-8') as file:
    CONFIG = yaml.safe_load(file)

# Load environment variables
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))
