import asyncio
import base64
import json
import os
import platform
import queue
import yaml
import numpy as np
import sounddevice as sd
import soundfile as sf
import websockets
import openwakeword
from openwakeword.model import Model
from dotenv import load_dotenv

# Load configuration
SCRIPT_PATH = os.path.dirname(os.path.realpath(__file__))
MODELS_PATH = os.path.join(SCRIPT_PATH, 'models')
SOUNDS_PATH = os.path.join(SCRIPT_PATH, 'sounds')

with open(os.path.join(SCRIPT_PATH, 'config.yml'), 'r', encoding='utf-8') as file:
    CONFIG = yaml.safe_load(file)

load_dotenv(os.path.join(SCRIPT_PATH, '.env'))

def play_sound(filename):
    """Play a sound file using sounddevice"""
    path = os.path.join(SOUNDS_PATH, filename)
    if not os.path.exists(path):
        print(f"❌ Sound file not found: {path}")
        return
    
    try:
        data, fs = sf.read(path)
        if platform.system() == 'Linux':
            sd.check_output_settings(channels=1)
        sd.play(data, fs)
    except Exception as e:
        print(f"❌ Sound playback error: {e}")

class WakeWordDetector:
    """Wake word detection using OpenWakeWord"""
    
    def __init__(self, config):
        self.config = config
        self.framework = None
        self.model = None
        self._initialize_model()
    
    def _initialize_model(self):
        """Initialize required models once"""
        openwakeword.utils.download_models()
        
        self.framework = 'tflite' if platform.machine().lower() in ['aarch64', 'armv7l'] else 'onnx'
        
        model_paths = []
        for lang_config in self.config['languages'].values():
            model_name = lang_config['model']
            model_path = os.path.join(MODELS_PATH, f"{model_name}.{self.framework}")
            model_paths.append(model_path)
        
        self.model = Model(
            wakeword_models=model_paths,
            inference_framework=self.framework
        )
    
    def listen_for_wake_word(self):
        """Listen for wake word and return detected wake word"""
        
        self._initialize_model() 
        print(f"🎙️  Listening for wake word using {self.framework.upper()} model...")
        frames = queue.Queue()
        
        def audio_callback(indata, *_):
            frames.put(indata.copy())

        threshold = self.config['openwakeword']['threshold']
        sample_rate = self.config['openwakeword']['sample_rate']
        frame_size = self.config['openwakeword']['frame_size']
        
        try:
            with sd.InputStream(samplerate=sample_rate,
                                blocksize=frame_size,
                                channels=1,
                                dtype='int16',
                                callback=audio_callback):
                while True:
                    frame = frames.get()
                    frame_flat = frame[:, 0].flatten() # mono channel
                    prediction = self.model.predict(frame_flat)
                    
                    for wake_word, score in prediction.items():
                        if score > threshold:
                            print(f"⏰ Wake word detected: {wake_word} (score: {score:.2f})")
                            return wake_word
        except Exception as e:
            print(f"❌ Audio input error: {e}")
            raise

class ConversationSession:
    """Conversation session with OpenAI Realtime API"""
    
    def __init__(self, config, language = 'korean'):
        self.config = config
        self.language = language
        self.sleep_words = [lang_config['sleep_word'].lower() for lang_config in self.config['languages'].values()]
        self.websocket = None
        self.response_chunks = []
        self.recording = True
        self.audio_queue = queue.Queue()
        self.stream = None
    
    async def connect(self):
        """Connect to OpenAI Realtime API"""
        print("🌐 Establishing connnection to Realtime API...")
        openai_key = os.getenv('OPENAI_API_KEY')
        if not openai_key:
            raise ValueError("OPENAI_API_KEY environment variable not set. Please add it to your .env file.")
        try:
            headers = {"Authorization": f"Bearer {openai_key}"}
            uri = f"wss://api.openai.com/v1/realtime?model={self.config['openai']['model']}"
            self.websocket = await websockets.connect(uri, additional_headers=headers)
            await self._send_session_config()
        except Exception as e:
            print(f"❌ Failed to connect to OpenAI API: {e}")
            raise
    
    async def _send_session_config(self):
        """Send session configuration with language-specific instructions"""
        instruction_params = self.config['languages'][self.language]
        instruction_params['user_age'] = self.config['conversation']['user_age']
        instructions = self.config['openai']['instruction_template'].format(**instruction_params)
        print(f'==> instructions: {instructions}')
        session_config = self.config['openai']['session_config'].copy()
        session_config['session']['instructions'] = instructions
        await self.websocket.send(json.dumps(session_config))
    
    def _setup_audio_capture(self):
        """Set up audio capture with callback"""
        def audio_callback(indata, *_):
            if self.recording:
                audio_data = (indata * 32767).astype(np.int16)
                self.audio_queue.put(audio_data)
        
        self.stream = sd.InputStream(
            samplerate=24000,
            channels=1,
            dtype='float32',
            callback=audio_callback,
            blocksize=1024
        )
    
    async def _process_audio_stream(self):
        """Process audio from queue and send"""
        while self.recording:
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
            
            if platform.system() == 'Linux':
                sd.check_output_settings(channels=1)
            sd.play(audio_np, samplerate=24000)
    
    async def _handle_message(self, data):
        """Handle incoming message from OpenAI"""
        message_type = data.get("type")
        
        # Additional logging when DEBUG is enabled
        if bool(os.environ.get('DEBUG')) and message_type not in {"response.output_audio.delta", "response.output_audio_transcript.delta"}:
            print(f"💬 Received message: {message_type}")
        
        match message_type:
            case "input_audio_buffer.speech_started":
                sd.stop()
                self.response_chunks.clear()
                
            case "input_audio_buffer.speech_stopped":
                play_sound(self.config['sounds']['sent'])
                
            case "conversation.item.input_audio_transcription.completed":
                transcript = data.get("transcript", "")
                print(f"🗣️  You said: {transcript}")
                
                transcript_lower = transcript.strip().lower().replace(',', '')
                if any(sleep_word in transcript_lower for sleep_word in self.sleep_words):
                    self.recording = False
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
                    
            case "error":
                print(f"❌ OpenAI API Error: {data}")
                self.recording = False
                return "error"
        
        return None
    
    def _cleanup(self):
        """Clean up audio resources"""
        self.recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
    
    async def run(self):
        """Run the complete conversation session"""
        audio_task = None
        try:
            await self.connect()
            self._setup_audio_capture()
            
            play_sound(self.config['sounds']['awake'])
            self.stream.start()
            print("👂 Choco is listening...")
            
            # Start audio processing task
            audio_task = asyncio.create_task(self._process_audio_stream())
            timeout = self.config['conversation']['timeout_seconds']
            
            while self.recording:
                try:
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=timeout)
                    data = json.loads(message)
                    result = await self._handle_message(data)

                    if result in {"goodbye", "error"}:
                        break
                        
                except asyncio.TimeoutError:
                    print(f"⏲️  Session timeout reached ({timeout}s of inactivity)")
                    self.recording = False
                    break
                    
        except Exception as e:
            print(f"⚠️  Error during conversation: {e}")
        finally:
            self.recording = False
            if audio_task:
                audio_task.cancel()
            self._cleanup()
            if self.websocket:
                await self.websocket.close()

class ChocoPi:
    def __init__(self, config):
        self.config = config
        self.wake_word_detector = WakeWordDetector(config)
        self.wake_words = [lang_config['wake_word'].lower() for lang_config in self.config['languages'].values()]
    
    def _get_wake_word_language(self, wake_word):
        """Get language configuration based on detected wake word"""
        for lang, config in self.config['languages'].items():
            if wake_word == config['model']:
                print(f"⚙️  Session configured for: {config['language_name']}")
                return lang
        
        default_lang = list(self.config['languages'].keys())[0]
        print(f"⚠️  Unknown wake word: '{wake_word}'. Using default language: {default_lang}")

        return default_lang
    
    def run(self):
        """Run the main application loop"""
        print(f"✨ Choco is ready! Say one of '{', '.join(self.wake_words)}' to start or end a conversation.")
        
        try:
            while True:
                if wake_word := self.wake_word_detector.listen_for_wake_word():
                    lang = self._get_wake_word_language(wake_word)
                    session = ConversationSession(self.config, lang)
                    asyncio.run(session.run())
                    
                    play_sound(self.config['sounds']['bye'])
                    print("✅ Session ended.\n")
                    
        except KeyboardInterrupt:
            print("👋 Shutting down...")

def main():
    app = ChocoPi(CONFIG)
    app.run()

if __name__ == '__main__':
    main()
