"""Audio management for playback and recording"""
import os
import logging
import numpy as np
import sounddevice as sd
import soundfile as sf
from chocopi.config import CONFIG, SOUNDS_PATH

logger = logging.getLogger(__name__)


class AudioManager:
    """Audio manager that supports simultaneous playback and recording"""

    def __init__(self):
        self.input_stream = None

    def start_recording(self, sample_rate, dtype, blocksize, callback, input_gain=1.0):
        """Start recording"""
        # Stop existing stream if present
        if self.input_stream:
            self.input_stream.stop()
            self.input_stream.close()

        # Wrap callback to apply input gain if applicable
        def gain_callback(indata, frames, time, status):
            if input_gain != 1.0:
                # Apply gain
                processed = indata.astype(np.float32) * input_gain

                # Handle clipping
                if dtype == 'int16':
                    max_val = np.max(np.abs(processed))
                    if max_val > 32767:
                        logger.debug("🔇 Input clipping detected (max: %.0f)", max_val)
                    processed = np.clip(processed, -32768, 32767).astype(np.int16)

                callback(processed, frames, time, status)
            else:
                callback(indata, frames, time, status)

        self.input_stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype=dtype,
            blocksize=blocksize,
            callback=gain_callback
        )
        self.input_stream.start()

    def stop_recording(self):
        """Stop recording and clean up"""
        if self.input_stream:
            self.input_stream.stop()
            self.input_stream.close()
            self.input_stream = None

    def start_playing(self, data, sample_rate=24000, blocksize=4096):
        """Play audio file or data (non-blocking)"""
        try:
            # Convert data to numpy array
            if isinstance(data, str):
                path = data if data.startswith('/') else os.path.join(SOUNDS_PATH, data)
                file_data, fs = sf.read(path)
                sd.play(file_data, fs, blocksize=blocksize)
            elif isinstance(data, bytes):
                audio_np = np.frombuffer(data, dtype=np.int16)
                sd.play(audio_np, sample_rate, blocksize=blocksize)
            else:
                sd.play(data, sample_rate, blocksize=blocksize)
        except Exception as e:
            logger.error("❌ Audio playback error: %s", e)

    def stop_playing(self):
        """Stops playback if active"""
        try:
            sd.stop()
        except Exception as e:
            logger.warning("⚠️  Error stopping playback: %s", e)

    def is_playing(self):
        """Check if audio is currently playing"""
        try:
            return sd.get_stream().active
        except:
            return False


# Global audio manager instance
AUDIO = AudioManager()
