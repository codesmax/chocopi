"""Profile configuration helpers"""
import logging
from chocopi.config import CONFIG

logger = logging.getLogger(__name__)


def get_active_profile():
    profiles = CONFIG.get("profiles", {})
    active_name = CONFIG.get("active_profile")
    if not active_name:
        raise ValueError("active_profile is not set in config.yml")
    if active_name not in profiles:
        raise ValueError(f"active_profile '{active_name}' not found in profiles")
    return profiles[active_name]


def get_profile_languages(profile):
    native = profile.get("native_language")
    learning = profile.get("learning_languages", {})
    languages = set(learning.keys())
    if native:
        languages.add(native)
    return languages
