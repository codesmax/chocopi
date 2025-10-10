"""Wake word detection using OpenWakeWord"""
import os
import queue
import logging
import openwakeword
from openwakeword.model import Model
from chocopi.config import CONFIG, IS_PI, MODELS_PATH
from chocopi.audio import AUDIO

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """On-device wake word detection using OpenWakeWord"""

    def __init__(self):
        self.framework = 'tflite' if IS_PI else 'onnx'
        self.model_paths = []
        for lang_config in CONFIG['languages'].values():
            model_name = lang_config['model']
            model_path = os.path.join(MODELS_PATH, f"{model_name}.{self.framework}")
            self.model_paths.append(model_path)

        # Download required models once if needed
        openwakeword.utils.download_models()

        self.model = Model(
            inference_framework=self.framework,
            wakeword_models=self.model_paths,
        )

    def listen(self):
        """Listen for wake word and return detected wake word"""

        # Reset prediction and audio feature buffers
        self.model.reset()

        logger.info("🎙️  Listening for wake word using %s model...", self.framework.upper())
        oww_config = CONFIG['openwakeword']
        frames = queue.Queue()

        def audio_callback(processed_audio, *_):
            frames.put(processed_audio)

        try:
            AUDIO.start_recording(
                sample_rate=oww_config['sample_rate'],
                dtype='int16',
                blocksize=int(oww_config['sample_rate'] * oww_config['frame_len_ms'] / 1000),
                callback=audio_callback
            )
            while True:
                try:
                    frame = frames.get(timeout=0.1)
                except queue.Empty:
                    continue

                frame_flat = frame[:, 0].flatten() # mono channel
                prediction = self.model.predict(frame_flat)
                for wake_word, score in prediction.items():
                    if score > oww_config['threshold']:
                        logger.info("⏰ Wake word detected: %s (score: %.2f)", wake_word, score)
                        logger.debug("Prediction items: %s", prediction.items())
                        AUDIO.stop_recording()
                        return wake_word
                    else:
                        if score > 0.1:
                            logger.debug("🔍 Wake word %s (score: %.2f)", wake_word, score)
        except Exception as e:
            logger.error("❌ Audio input error: %s", e)
            raise
        finally:
            AUDIO.stop_recording()
