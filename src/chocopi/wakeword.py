"""Wake word detection using OpenWakeWord"""
import asyncio
import os
import logging
import openwakeword
from openwakeword.model import Model
from chocopi.config import CONFIG, IS_PI, MODELS_PATH
from chocopi.audio import AUDIO

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """On-device wake word detection using OpenWakeWord"""

    def __init__(self):
        self.config = CONFIG['openwakeword']
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
            vad_threshold=self.config['vad_threshold'],
        )

    async def listen(self):
        """Listen for wake word and return detected wake word"""

        # Reset prediction and audio feature buffers
        self.model.reset()

        logger.info("🎙️  Listening for wake word using %s model...", self.framework.upper())
        audio_queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def audio_callback(processed_audio, *_):
            loop.call_soon_threadsafe(audio_queue.put_nowait, processed_audio)

        try:
            blocksize = int(self.config['sample_rate'] * self.config['chunk_duration_ms'] / 1000)
            input_gain = self.config.get('input_gain', CONFIG['audio']['input_gain'])

            AUDIO.start_recording(
                sample_rate=self.config['sample_rate'],
                dtype='int16',
                blocksize=blocksize,
                input_gain=input_gain,
                callback=audio_callback
            )
            logger.debug("🔊 Wake word recording started (sample_rate=%d, blocksize=%d, input_gain=%.1f)", self.config['sample_rate'], blocksize, input_gain)

            while True:
                chunk = await audio_queue.get()
                chunk_flat = chunk[:, 0].flatten() # mono channel
                prediction = self.model.predict(chunk_flat)
                for wake_word, score in prediction.items():
                    if score > self.config['threshold']:
                        logger.info("⏰ Wake word activated: %s (score: %.2f)", wake_word, score)
                        logger.debug("Prediction items: %s", prediction.items())
                        AUDIO.stop_recording()
                        return wake_word
                    else:
                        if score > 0.01:
                            logger.debug("🔍 Wake word detected: %s (score: %.2f)", wake_word, score)
        except Exception as e:
            logger.error("❌ Audio input error: %s", e)
            raise
        finally:
            AUDIO.stop_recording()
