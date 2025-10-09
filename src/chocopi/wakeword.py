"""Wake word detection using OpenWakeWord"""
import os
import queue
import openwakeword
from openwakeword.model import Model
from chocopi.config import CONFIG, DEBUG, IS_PI, MODELS_PATH
from chocopi.audio import AUDIO


class WakeWordDetector:
    """Wake word detection using OpenWakeWord"""

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

    def listen_for_wake_word(self):
        """Listen for wake word and return detected wake word"""

        # Reset prediction and audio feature buffers
        self.model.reset()

        print(f"🎙️  Listening for wake word using {self.framework.upper()} model...")
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
                        print(f"⏰ Wake word detected: {wake_word} (score: {score:.2f})")
                        if DEBUG:
                            print(prediction.items())
                        AUDIO.stop_recording()
                        return wake_word
                    else:
                        if score > 0.1 and DEBUG:
                            print(f"🔍 Wake word {wake_word} (score: {score:.2f})")
        except Exception as e:
            print(f"❌ Audio input error: {e}")
            raise
        finally:
            AUDIO.stop_recording()
