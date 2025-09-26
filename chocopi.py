import asyncio
import base64
import json
import os
import platform
import queue
import re
import yaml
import numpy as np
import sounddevice as sd
import soundfile as sf
import websockets
import openwakeword
from openwakeword.model import Model
from dotenv import load_dotenv
from rapidfuzz import fuzz

# Load configuration
SCRIPT_PATH = os.path.dirname(os.path.realpath(__file__))
MODELS_PATH = os.path.join(SCRIPT_PATH, 'models')
SOUNDS_PATH = os.path.join(SCRIPT_PATH, 'sounds')

with open(os.path.join(SCRIPT_PATH, 'config.yml'), 'r', encoding='utf-8') as file:
    CONFIG = yaml.safe_load(file)

load_dotenv(os.path.join(SCRIPT_PATH, '.env'))
class AudioManager:
    """Audio manager for playback and recording"""

    def __init__(self):
        self.input_gain = CONFIG['audio']['input_gain']
        self.input_stream = None

    def record(self, sample_rate, dtype, blocksize, callback):
        """Start recording (stops any existing recording first)"""
        # Stop any existing recording first
        if self.input_stream:
            self.stop()

        def gain_callback(indata, *args):
            # Apply input gain consistently
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

    def stop(self):
        """Stop recording and clean up"""
        if self.input_stream:
            print("🔴 [AudioManager] Stopping audio input...")
            self.input_stream.stop()
            self.input_stream.close()
            self.input_stream = None

    def play(self, data, sample_rate=None):
        """Playback of sound files or raw audio data"""
        try:
            if isinstance(data, str):
                if not data.startswith('/'):
                    data = os.path.join(SOUNDS_PATH, data)
                audio_data, fs = sf.read(data)
                sd.play(audio_data, fs)
            else:
                sd.play(data, sample_rate or 24000)
        except Exception as e:
            print(f"❌ Audio playback error: {e}")

AUDIO = AudioManager()
class WakeWordDetector:
    """Wake word detection using OpenWakeWord"""

    def __init__(self):
        self.framework = 'tflite' if platform.machine().lower() in ['aarch64', 'armv7l'] else 'onnx'
        self.model = None
        # Download required models once if needed
        openwakeword.utils.download_models()
        self._initialize_model()

    def _initialize_model(self):
        model_paths = []
        for lang_config in CONFIG['languages'].values():
            model_name = lang_config['model']
            model_path = os.path.join(MODELS_PATH, f"{model_name}.{self.framework}")
            model_paths.append(model_path)

        self.model = Model(
            wakeword_models=model_paths,
            inference_framework=self.framework
        )

    def listen_for_wake_word(self):
        """Listen for wake word and return detected wake word"""
        self.model.reset()

        print(f"🎙️  Listening for wake word using {self.framework.upper()} model...")
        oww_config = CONFIG['openwakeword']
        frames = queue.Queue()

        def audio_callback(processed_audio, *_):
            frames.put(processed_audio)

        try:
            AUDIO.record(
                sample_rate=oww_config['sample_rate'],
                dtype='int16',
                blocksize=int(oww_config['sample_rate'] * oww_config['frame_len_ms'] / 1000),
                callback=audio_callback
            )
            while True:
                frame = frames.get()
                frame_flat = frame[:, 0].flatten() # mono channel
                prediction = self.model.predict(frame_flat)

                for wake_word, score in prediction.items():
                    if score > oww_config['threshold']:
                        print(f"⏰ Wake word detected: {wake_word} (score: {score:.2f})")
                        AUDIO.stop()
                        return wake_word
        except Exception as e:
            print(f"❌ Audio input error: {e}")
            raise
        finally:
            AUDIO.stop()

class ConversationSession:
    """Conversation session with OpenAI Realtime API"""

    def __init__(self, learning_language = 'ko'):
        self.lang_config = CONFIG['languages'][learning_language]
        self.websocket = None
        self.response_chunks = []
        self.is_recording = True
        self.audio_queue = queue.Queue()

    async def connect(self):
        """Connect to OpenAI Realtime API"""
        print("🌐 Establishing connnection to Realtime API...")
        openai_key = os.getenv('OPENAI_API_KEY')
        if not openai_key:
            raise ValueError("OPENAI_API_KEY environment variable not set. Please add it to your .env file.")
        try:
            headers = {"Authorization": f"Bearer {openai_key}"}
            uri = f"wss://api.openai.com/v1/realtime?model={CONFIG['openai']['model']}"
            self.websocket = await websockets.connect(uri, additional_headers=headers)
            await self._send_session_config()
            await self.websocket.send(json.dumps(CONFIG['openai']['greeting_config']))
        except Exception as e:
            print(f"❌ Failed to connect to OpenAI API: {e}")
            raise

    async def _send_session_config(self):
        """Send session configuration with language-specific instructions"""
        instruction_params = {}
        instruction_params['user_age'] = CONFIG['user_age']
        instruction_params['native_language'] = CONFIG['languages'][CONFIG['native_language']]['language_name']
        instruction_params['learning_language'] = self.lang_config['language_name']
        instruction_params['comprehension_age'] = self.lang_config['comprehension_age']
        instruction_params['sleep_word'] = self.lang_config['sleep_word']
        instructions = CONFIG['openai']['session_instructions'].format(**instruction_params)
        transcription_prompt = CONFIG['openai']['transcription_prompt'].format(**instruction_params)
        if bool(os.environ.get('DEBUG')):
            print(f'⚙️  Session instructions: {instructions}')
            print(f'⚙️  Transcription prompt: {transcription_prompt}')
        session_config = CONFIG['openai']['session_config'].copy()
        session_config['session']['instructions'] = instructions
        session_config['session']['audio']['input']['transcription']['prompt'] = transcription_prompt
        await self.websocket.send(json.dumps(session_config))

    def _setup_audio_capture(self):
        """Set up audio capture with callback"""
        def audio_callback(processed_audio, *_):
            if self.is_recording:
                # Convert processed float32 audio to int16 for OpenAI API
                audio_data = (processed_audio * 32767).astype(np.int16)
                self.audio_queue.put(audio_data)

        AUDIO.record(
            sample_rate=24000,
            dtype='float32',
            blocksize=1024,
            callback=audio_callback
        )

    async def _process_audio_stream(self):
        """Process audio from queue and send"""
        while self.is_recording:
            if not self.audio_queue.empty():
                try:
                    audio_data = self.audio_queue.get_nowait()
                    audio_base64 = base64.b64encode(audio_data.tobytes()).decode('utf-8')
                    message = {"type": "input_audio_buffer.append", "audio": audio_base64}
                    await self.websocket.send(json.dumps(message))
                except queue.Empty:
                    pass
            await asyncio.sleep(0.01)

    def _play_response_audio(self):
        """Play collected audio response"""
        if self.response_chunks:
            combined_audio = b''.join(self.response_chunks)
            audio_np = np.frombuffer(combined_audio, dtype=np.int16)
            AUDIO.play(audio_np, 24000)

    def _is_sleep_word(self, text, threshold=85):
        """Check if text contains a sleep word using fuzzy matching"""
        sleep_word = self.lang_config['sleep_word'].lower()
        if not text or not sleep_word:
            return False

        filtered_text = re.sub(r'[,.!?]', '', text.strip().lower())
        score = fuzz.partial_ratio(sleep_word, filtered_text)
        if score >= threshold:
            if bool(os.environ.get('DEBUG')):
                print(f"✅ Sleep word fuzzy matched: '{sleep_word}' (score: {score})")
            return True
        return False

    async def _handle_message(self, data, blocking_response=False):
        """Handle incoming message from OpenAI"""
        message_type = data.get("type")

        # Additional logging when DEBUG is enabled
        if bool(os.environ.get('DEBUG')) and message_type not in {"response.output_audio.delta", "response.output_audio_transcript.delta"}:
            print(f"💬 Received message: {message_type}")

        match message_type:
            case "input_audio_buffer.speech_started":
                # User is speaking; interrupt any ongoing response
                sd.stop()
                self.response_chunks.clear()

            case "input_audio_buffer.speech_stopped":
                AUDIO.play(CONFIG['sounds']['sent'])

            case "conversation.item.input_audio_transcription.completed":
                transcript = data.get("transcript", "")
                if "[PROMPT]" in transcript:
                    return None

                print(f"🗣️  You said: {transcript}")
                # Check for sleep words using fuzzy matching
                if self._is_sleep_word(transcript, CONFIG['session']['sleep_word_threshold']):
                    print(f"💤 Sleep word detected: '{transcript}'")
                    self.is_recording = False
                    return "goodbye"

            case "response.output_audio.delta":
                if audio_base64 := data.get("delta", ""):
                    audio_bytes = base64.b64decode(audio_base64)
                    self.response_chunks.append(audio_bytes)

            case "response.output_audio_transcript.done":
                transcript = data.get("transcript", "")
                print(f"🤖 Choco says: {transcript}")

            case "response.done":
                self._play_response_audio()
                self.response_chunks.clear()
                if blocking_response:
                    sd.wait()
                    return "done"

            case "error":
                print(f"❌ OpenAI API Error: {data}")
                self.is_recording = False
                return "error"

        return None

    async def run(self):
        """Run conversation session"""
        timeout = CONFIG['session']['timeout_seconds']
        audio_task = None
        try:
            await self.connect()
            while True:
                try:
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=5)
                    data = json.loads(message)
                    result = await self._handle_message(data, blocking_response=True)
                    if result == "done":
                        break
                except asyncio.TimeoutError:
                    print("⚠️  Timeout waiting for greeting response")
                    break

            self._setup_audio_capture()
            print("👂 Choco is listening...")

            audio_task = asyncio.create_task(self._process_audio_stream())
            while self.is_recording:
                try:
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=timeout)
                    data = json.loads(message)
                    result = await self._handle_message(data)
                    if result in {"goodbye", "error"}:
                        break
                except asyncio.TimeoutError:
                    print(f"⏲️  Session timeout reached ({timeout}s of inactivity)")
                    break

        except Exception as e:
            print(f"⚠️  Error during conversation: {e}")
        finally:
            self.is_recording = False
            if audio_task:
                audio_task.cancel()
            AUDIO.stop()
            if self.websocket:
                await self.websocket.close()

class ChocoPi:
    def __init__(self):
        self.wake_word_detector = WakeWordDetector()
        self.wake_words = [lang_config['wake_word'].lower() for lang_config in CONFIG['languages'].values()]

    def _get_wake_word_language(self, wake_word):
        """Get language configuration based on detected wake word"""
        for lang, config in CONFIG['languages'].items():
            if wake_word == config['model'] and lang != CONFIG['native_language']:
                print(f"⚙️  Session configured for: {config['language_name']}")
                return lang

        default_lang = list(CONFIG['languages'].keys())[0]
        print(f"⚠️  Unknown wake word: '{wake_word}'. Using default language: {default_lang}")

        return default_lang

    def run(self):
        """Run the main application loop"""
        print(f"✨ Choco is ready! Say one of '{', '.join(self.wake_words)}' to start or end a conversation.")

        try:
            while True:
                if wake_word := self.wake_word_detector.listen_for_wake_word():
                    lang = self._get_wake_word_language(wake_word)
                    AUDIO.play(CONFIG['sounds']['awake'])

                    session = ConversationSession(lang)
                    asyncio.run(session.run())

                    AUDIO.play(CONFIG['sounds']['bye'])
                    print("✅ Session ended.\n")

        except KeyboardInterrupt:
            print("👋 Shutting down...")

def main():
    app = ChocoPi()
    app.run()

if __name__ == '__main__':
    main()
