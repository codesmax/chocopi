"""Conversation session with OpenAI Realtime API"""
import asyncio
import base64
import json
import os
import queue
import re
import threading
import numpy as np
import sounddevice as sd
import websockets
from enum import Enum
from rapidfuzz import fuzz
from chocopi.config import CONFIG, DEBUG
from chocopi.audio import AUDIO


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

        if DEBUG:
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
            print(f"🔊 Reponse playback started")

            # Always use non-blocking playback
            AUDIO.start_playing(audio_np, CONFIG['openai']['sample_rate'], blocking=self.blocking_response)

            # Spawn thread to monitor completion and stop animation
            def wait_for_completion():
                sd.wait()  # Wait for playback to finish
                if self.display:
                    self.display.set_speaking(False)
                print(f"🔊 Response playback finished")

            threading.Thread(target=wait_for_completion, daemon=True).start()

    def _is_sleep_word(self, text, threshold=85):
        """Check if text contains a sleep word using fuzzy matching"""
        sleep_word = self.lang_config['sleep_word'].lower()
        if not text or not sleep_word:
            return False

        filtered_text = re.sub(r'[,.!?]', '', text.strip().lower())
        score = fuzz.ratio(sleep_word, filtered_text)
        if score >= threshold:
            if DEBUG:
                print(f"✅ Sleep word fuzzy matched: '{sleep_word}' (score: {score})")
            return True
        return False

    async def _handle_message(self, data):
        """Handle incoming message from OpenAI"""
        Result = self.Result
        message_type = data.get("type")

        # Additional logging when DEBUG is enabled
        if DEBUG and message_type not in {"response.output_audio.delta", "response.output_audio_transcript.delta"}:
            print(f"💬 Received message: {message_type}")

        match message_type:
            case "input_audio_buffer.speech_started":
                print("🔊 VAD: user speech started")

                # User is speaking; interrupt any ongoing response
                AUDIO.stop_playing()
                self.response_chunks.clear()

                # Stop speaking animation when interrupted
                if self.display:
                    self.display.set_speaking(False)

            case "input_audio_buffer.speech_stopped":
                print("🔊 VAD: user speech ended")

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
                if self.display:
                    self.display.set_speaking(True)

                self._play_response()
                self.response_chunks.clear()

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
