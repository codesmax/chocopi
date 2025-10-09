"""Configuration loading and constants"""
import os
import platform
import yaml
from dotenv import load_dotenv

# Environment
DEBUG = bool(os.environ.get('DEBUG'))
IS_PI = platform.machine().lower() in ['aarch64', 'armv7l']
SCRIPT_PATH = os.path.dirname(os.path.realpath(__file__))
MODELS_PATH = os.path.join(SCRIPT_PATH, 'models')
SOUNDS_PATH = os.path.join(SCRIPT_PATH, 'sounds')

# Load configuration
with open(os.path.join(SCRIPT_PATH, 'config.yml'), 'r', encoding='utf-8') as file:
    CONFIG = yaml.safe_load(file)

# Load environment variables
load_dotenv(os.path.join(SCRIPT_PATH, '.env'))
