"""Audio management for playback and recording"""
import asyncio
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

    def start_recording(self, sample_rate, dtype, blocksize, callback):
        """Start recording"""
        # Limit to one recording stream
        if self.input_stream:
            self.stop_recording()

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

    async def start_playing(self, data, sample_rate=24000, blocksize=4096):
        """Non-blocking audio playback"""
        def _play():
            try:
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

        await asyncio.to_thread(_play)

    def stop_playing(self):
        """Stops playback if active"""
        if sd.get_stream().active:
            sd.stop()

    async def wait_for_playback(self):
        """Wait for current playback to complete"""
        await asyncio.to_thread(sd.wait)


# Global audio manager instance
AUDIO = AudioManager()
