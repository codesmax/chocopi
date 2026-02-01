"""Language detection helpers"""
import logging
from lingua import Language, LanguageDetectorBuilder
from chocopi.config import CONFIG

logger = logging.getLogger(__name__)

LANGUAGE_MAP = {
    "en": Language.ENGLISH,
    "es": Language.SPANISH,
    "ko": Language.KOREAN,
    "zh": Language.CHINESE,
}


def _build_detector():
    supported = [
        LANGUAGE_MAP[code]
        for code in CONFIG["languages"].keys()
        if code in LANGUAGE_MAP
    ]
    if not supported:
        supported = list(LANGUAGE_MAP.values())
    return LanguageDetectorBuilder.from_languages(*supported).build()


_DETECTOR = _build_detector()


def warm_language_detector():
    try:
        _DETECTOR.detect_language_of("hello")
    except Exception as exc:
        logger.debug("Language detector warmup failed: %s", exc)


def detect_language_code(text):
    if not text:
        return "und"

    detected = _DETECTOR.detect_language_of(text)
    if detected is None:
        return "und"

    iso_639_1 = detected.iso_code_639_1
    if iso_639_1 is not None:
        return iso_639_1.name.lower()

    iso_639_3 = detected.iso_code_639_3
    if iso_639_3 is None:
        return "und"
    return iso_639_3.name.lower()
