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
        self.input_gain = CONFIG['audio']['input_gain']
        self.input_stream = None

    def start_recording(self, sample_rate, dtype, blocksize, callback):
        """Start recording"""
        # Limit to one recording stream
        if self.input_stream:
            self.stop_recording()

        def gain_callback(indata, *args):
            # Apply input gain with clipping protection
            if self.input_gain != 1.0:
                processed = indata * self.input_gain
                processed = np.clip(processed, -32768, 32767).astype(np.int16)
            else:
                processed = indata.copy()
            callback(processed, *args)

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

    def start_playing(self, data, sample_rate=24000, blocksize=4096, interruptible=True):
        """Playback of sound files or raw audio data"""
        try:
            if isinstance(data, str):
                if not data.startswith('/'):
                    data = os.path.join(SOUNDS_PATH, data)
                audio_data, fs = sf.read(data)
                sd.play(audio_data, fs, blocksize=blocksize, blocking=not interruptible)
            else:
                sd.play(data, sample_rate, blocksize=blocksize, blocking=not interruptible)
        except Exception as e:
            logger.error("❌ Audio playback error: %s", e)

    def stop_playing(self):
        """Stops playback if active"""
        if sd.get_stream().active:
            sd.stop()


# Global audio manager instance
AUDIO = AudioManager()
