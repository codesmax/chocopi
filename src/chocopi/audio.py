"""Audio management for playback and recording"""
import os
import sounddevice as sd
import soundfile as sf
from chocopi.config import CONFIG, SOUNDS_PATH


class AudioManager:
    """Audio manager for playback and recording"""

    def __init__(self):
        self.input_gain = CONFIG['audio']['input_gain']
        self.input_stream = None

    def start_recording(self, sample_rate, dtype, blocksize, callback):
        """Start recording"""
        if self.input_stream:
            self.stop_recording()

        def gain_callback(indata, *args):
            # Apply input gain
            processed = indata * self.input_gain if self.input_gain != 1.0 else indata.copy()
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

    def start_playing(self, data, sample_rate=24000, blocking=False):
        """Playback of sound files or raw audio data"""
        try:
            if isinstance(data, str):
                if not data.startswith('/'):
                    data = os.path.join(SOUNDS_PATH, data)
                audio_data, fs = sf.read(data)
                sd.play(audio_data, fs, blocking=blocking)
            else:
                sd.play(data, sample_rate, blocking=blocking)
        except Exception as e:
            print(f"❌ Audio playback error: {e}")

    def stop_playing(self):
        """Stops playback if active"""
        if sd.get_stream().active:
            sd.stop()


# Global audio manager instance
AUDIO = AudioManager()
