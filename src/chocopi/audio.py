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

    def start_recording(self, sample_rate, dtype, blocksize, input_gain, callback):
        """Start recording"""
        # Limit to one recording stream
        if self.input_stream:
            self.stop_recording()

        def gain_callback(indata, *args):
            if input_gain != 1.0:
                processed = indata * input_gain

                # Clip to range based on dtype
                max_val = np.max(np.abs(processed))
                if dtype == 'float32':  # -1.0..1.0
                    if max_val > 1.0:
                        logger.debug("🔇 Clipping detected: max value %.3f before clipping (gain=%.1f)",
                                    max_val, input_gain)
                    processed = np.clip(processed, -1.0, 1.0)
                elif dtype == 'int16':  # -32768..32767
                    if max_val > 32767:
                        logger.debug("🔇 Clipping detected: max value %.0f before clipping (gain=%.1f)",
                                    max_val, input_gain)
                    processed = np.clip(processed, -32768, 32767).astype(np.int16)
                else:
                    logger.warning("❌ Unsupported dtype for input gain: %s", dtype)
                    processed = indata.copy()
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

    def start_playing(self, data, sample_rate=24000, blocksize=4096, blocking=False):
        """Playback of sound files or raw audio data"""
        try:
            if isinstance(data, str):
                if not data.startswith('/'):
                    data = os.path.join(SOUNDS_PATH, data)
                file_data, file_sample_rate = sf.read(data)
                sd.play(file_data, file_sample_rate, blocksize=blocksize, blocking=blocking)
            else:
                sd.play(data, sample_rate, blocksize=blocksize, blocking=blocking)
        except Exception as e:
            logger.error("❌ Audio playback error: %s", e)

    def stop_playing(self):
        """Stops playback if active"""
        if sd.get_stream().active:
            sd.stop()

    async def wait_for_playback(self):
        """Wait for current playback to complete"""
        await asyncio.to_thread(sd.wait)


# Global audio manager instance
AUDIO = AudioManager()
