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
        self.output_stream = None

    def start_recording(self, sample_rate, dtype, blocksize, callback):
        """Start recording"""
        # Stop existing stream if present
        if self.input_stream:
            self.input_stream.stop()
            self.input_stream.close()

        self.input_stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype=dtype,
            blocksize=blocksize,
            callback=callback
        )
        self.input_stream.start()

    def stop_recording(self):
        """Stop recording and clean up"""
        if self.input_stream:
            self.input_stream.stop()
            self.input_stream.close()
            self.input_stream = None

    def start_playing(self, data, sample_rate=24000, finished_callback=None):
        """Play audio file or data with optional completion callback"""
        try:
            # Stop existing playback if any
            if self.output_stream and self.output_stream.active:
                self.output_stream.stop()
                self.output_stream.close()

            # Convert data to numpy array
            if isinstance(data, str):
                path = data if data.startswith('/') else os.path.join(SOUNDS_PATH, data)
                audio_np, sample_rate = sf.read(path, dtype='int16')
            elif isinstance(data, bytes):
                audio_np = np.frombuffer(data, dtype=np.int16)
            else:
                audio_np = np.array(data, dtype=np.int16)

            # Ensure 1D array
            if audio_np.ndim > 1:
                audio_np = audio_np.flatten()

            # Create and start output stream
            self.output_stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype='int16',
                finished_callback=finished_callback
            )
            self.output_stream.start()
            self.output_stream.write(audio_np)

        except Exception as e:
            logger.error("❌ Audio playback error: %s", e)

    def stop_playing(self):
        """Stops playback if active"""
        try:
            if self.output_stream and self.output_stream.active:
                self.output_stream.stop()
                self.output_stream.close()
                self.output_stream = None
        except Exception as e:
            logger.warning("⚠️  Error stopping playback: %s", e)


# Global audio manager instance
AUDIO = AudioManager()
