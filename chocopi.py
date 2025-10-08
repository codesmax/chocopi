import asyncio
import base64
import json
import os
import platform
import queue
import re
import threading
import yaml
import numpy as np
import sounddevice as sd
import soundfile as sf
import websockets
import openwakeword
from enum import Enum
from openwakeword.model import Model
from dotenv import load_dotenv
from rapidfuzz import fuzz
from display import create_display_manager

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

    def start_recording(self, sample_rate, dtype, blocksize, callback):
        """Start recording"""
        # Stop any existing recording first
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

AUDIO = AudioManager()
class WakeWordDetector:
    """Wake word detection using OpenWakeWord"""

    def __init__(self):
        self.framework = 'tflite' if platform.machine().lower() in ['aarch64', 'armv7l'] else 'onnx'
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
                frame = frames.get()
                frame_flat = frame[:, 0].flatten() # mono channel
                prediction = self.model.predict(frame_flat)

                for wake_word, score in prediction.items():
                    if score > oww_config['threshold']:
                        print(f"⏰ Wake word detected: {wake_word} (score: {score:.2f})")
                        if bool(os.environ.get('DEBUG')):
                            print(prediction.items())
                        AUDIO.stop_recording()
                        return wake_word
        except Exception as e:
            print(f"❌ Audio input error: {e}")
            raise
        finally:
            AUDIO.stop_recording()

class ConversationSession:
    """Conversation session with OpenAI Realtime API"""

    class Result(Enum):
        """Result codes for message handling"""
        GREETED = "greeted"
        GOODBYE = "goodbye"
        ERROR = "error"

    def __init__(self, learning_language = 'ko', display_manager=None):
        self.lang_config = CONFIG['languages'][learning_language]
        self.websocket = None
        self.response_chunks = []
        self.audio_queue = queue.Queue()
        self.blocking_response = True
        self.is_active = True
        self.is_greeting = True
        self.is_terminating = False
        self.display = display_manager

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

            # Send session config
            await self._send_session_config()

            # Create and send greeting response to initiate conversation
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

        session_config = CONFIG['openai']['session_config'].copy()
        session_config['session']['instructions'] = instructions
        session_config['session']['audio']['input']['transcription']['prompt'] = transcription_prompt

        if bool(os.environ.get('DEBUG')):
            print(f'⚙️  Session instructions: {instructions}')
            print(f'⚙️  Transcription prompt: {transcription_prompt}')

        await self.websocket.send(json.dumps(session_config))

    def _start_listening(self):
        """Start audio capture with handler"""
        def audio_callback(processed_audio, *_):
            if self.is_active:
                self.audio_queue.put(processed_audio.astype(np.int16))

        AUDIO.start_recording(
            sample_rate=CONFIG['openai']['sample_rate'],
            dtype='int16',
            blocksize=int(CONFIG['openai']['sample_rate'] * CONFIG['openai']['frame_len_ms'] / 1000),
            callback=audio_callback
        )

    async def _process_audio(self):
        """Process audio from queue and send"""
        while self.is_active:
            if not self.audio_queue.empty():
                try:
                    audio_data = self.audio_queue.get_nowait()
                    audio_base64 = base64.b64encode(audio_data.tobytes()).decode('utf-8')
                    message = {"type": "input_audio_buffer.append", "audio": audio_base64}
                    await self.websocket.send(json.dumps(message))
                except queue.Empty:
                    pass
            await asyncio.sleep(0.01)

    def _play_response(self):
        """Play collected audio response and stop speaking animation when done"""
        if self.response_chunks:
            combined_audio = b''.join(self.response_chunks)
            audio_np = np.frombuffer(combined_audio, dtype=np.int16)
            AUDIO.start_playing(audio_np, CONFIG['openai']['sample_rate'], blocking=self.blocking_response)

            # If non-blocking playback, spawn thread to monitor completion
            if not self.blocking_response and self.display:
                def wait_for_completion():
                    sd.wait()  # Wait for playback to finish
                    self.display.set_speaking(False)

                threading.Thread(target=wait_for_completion, daemon=True).start()

    def _is_sleep_word(self, text, threshold=85):
        """Check if text contains a sleep word using fuzzy matching"""
        sleep_word = self.lang_config['sleep_word'].lower()
        if not text or not sleep_word:
            return False

        filtered_text = re.sub(r'[,.!?]', '', text.strip().lower())
        score = fuzz.ratio(sleep_word, filtered_text)
        if score >= threshold:
            if bool(os.environ.get('DEBUG')):
                print(f"✅ Sleep word fuzzy matched: '{sleep_word}' (score: {score})")
            return True
        return False

    async def _handle_message(self, data):
        """Handle incoming message from OpenAI"""
        Result = self.Result
        message_type = data.get("type")

        # Additional logging when DEBUG is enabled
        if bool(os.environ.get('DEBUG')) and message_type not in {"response.output_audio.delta", "response.output_audio_transcript.delta"}:
            print(f"💬 Received message: {message_type}")

        match message_type:
            case "input_audio_buffer.speech_started":
                # User is speaking; interrupt any ongoing response
                AUDIO.stop_playing()
                self.response_chunks.clear()

                # Stop speaking animation when interrupted
                if self.display:
                    self.display.set_speaking(False)

            case "input_audio_buffer.speech_stopped":
                AUDIO.start_playing(CONFIG['sounds']['sent'])

            case "conversation.item.input_audio_transcription.completed":
                transcript = data.get("transcript", "")
                print(f"🗣️  You said: {transcript}")

                # Add to display
                if self.display:
                    self.display.add_transcript("user", transcript)

                # Check for sleep words using fuzzy matching
                if self._is_sleep_word(transcript, CONFIG['session']['sleep_word_threshold']):
                    print(f"💤 Sleep word detected: '{transcript}'")

                    # Prepare to terminate session
                    self.blocking_response = True
                    self.is_terminating = True
                    AUDIO.stop_recording()

            case "response.output_audio.delta":
                if audio_base64 := data.get("delta", ""):
                    audio_bytes = base64.b64decode(audio_base64)
                    self.response_chunks.append(audio_bytes)

            case "response.output_audio_transcript.done":
                transcript = data.get("transcript", "")
                print(f"🤖 Choco says: {transcript}")

                # Add to display
                if self.display:
                    self.display.add_transcript("choco", transcript)

            case "response.done":
                # Start speaking animation before playback
                if self.display:
                    self.display.set_speaking(True)

                self._play_response()
                self.response_chunks.clear()

                # Speaking animation stops automatically when playback completes
                # (handled by background thread in _play_response)

                if self.is_greeting:
                    return Result.GREETED
                if self.is_terminating:
                    return Result.GOODBYE

            case "error":
                print(f"❌ OpenAI API Error: {data}")
                self.is_active = False
                AUDIO.stop_recording()
                return Result.ERROR

        return None

    async def run(self):
        """Run conversation session"""
        Result = self.Result
        audio_task = None
        try:
            await self.connect()
            while self.is_active:
                try:
                    # Short timeout for greeting, normal timeout for conversation
                    timeout = CONFIG['session']['greeting_timeout'] if self.is_greeting else CONFIG['session']['conversation_timeout']
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=timeout)
                    data = json.loads(message)
                    result = await self._handle_message(data)

                    # Transition to conversation after greeting
                    if self.is_greeting and result == Result.GREETED:
                        self.is_greeting = False
                        self.blocking_response = False
                        self._start_listening()
                        print("👂 Choco is listening...")
                        audio_task = asyncio.create_task(self._process_audio())
                        continue

                    # Handle exit conditions
                    if result in {Result.GOODBYE, Result.ERROR}:
                        self.is_active = False
                        break

                except asyncio.TimeoutError:
                    print("⚠️  Timeout waiting for greeting response" if self.is_greeting
                          else f"⏲️  Session timeout reached ({timeout}s of inactivity)")
                    self.is_active = False
                    break

        except Exception as e:
            print(f"⚠️  Error during conversation: {e}")
        finally:
            if audio_task:
                audio_task.cancel()
            AUDIO.stop_recording()
            if self.websocket:
                await self.websocket.close()

class ChocoPi:
    def __init__(self):
        self.wake_word_detector = WakeWordDetector()
        self.wake_words = [lang_config['wake_word'].lower() for lang_config in CONFIG['languages'].values()]
        self.display = create_display_manager(CONFIG)

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

        # Start display if enabled
        if self.display:
            self.display.start()

        try:
            while True:
                if wake_word := self.wake_word_detector.listen_for_wake_word():
                    lang = self._get_wake_word_language(wake_word)
                    AUDIO.start_playing(CONFIG['sounds']['awake'])

                    session = ConversationSession(lang, display_manager=self.display)
                    asyncio.run(session.run())

                    AUDIO.start_playing(CONFIG['sounds']['bye'])
                    print("✅ Session ended.\n")

        except KeyboardInterrupt:
            print("👋 Shutting down...")
        finally:
            if self.display:
                self.display.stop()

def main():
    app = ChocoPi()
    app.run()

if __name__ == '__main__':
    main()
