"""Conversation session with OpenAI Realtime API"""
import asyncio
import base64
import json
import logging
import os
import queue
import re
import numpy as np
import websockets
from enum import Enum
from rapidfuzz import fuzz
from chocopi.config import CONFIG
from chocopi.audio import AUDIO

logger = logging.getLogger(__name__)


class ConversationSession:
    """Conversation session with OpenAI Realtime API"""

    class Result(Enum):
        """Result codes for message handling"""
        GREETED = "greeted"
        GOODBYE = "goodbye"
        ERROR = "error"

    def __init__(self, learning_language = 'ko', display=None):
        self.lang_config = CONFIG['languages'][learning_language]
        self.websocket = None
        self.response_chunks = []
        self.audio_queue = queue.Queue()
        self.display = display
        self.is_active = True
        self.is_greeting = True
        self.is_terminating = False

    async def connect(self):
        """Connect to OpenAI Realtime API"""
        logger.info("🌐 Establishing connnection to Realtime API...")
        openai_key = os.getenv('OPENAI_API_KEY')
        if not openai_key:
            raise ValueError("OPENAI_API_KEY environment variable not set. Please add it to your .env file.")
        try:
            headers = {"Authorization": f"Bearer {openai_key}"}
            uri = f"wss://api.openai.com/v1/realtime?model={CONFIG['openai']['model']}"
            self.websocket = await websockets.connect(uri, additional_headers=headers)

            # Send session config
            await self._update_session()

            # Create and send greeting response to initiate conversation
            await self.websocket.send(json.dumps(CONFIG['openai']['greeting_config']))
        except Exception as e:
            logger.error("❌ Failed to connect to OpenAI API: %s", e)
            raise

    async def _update_session(self):
        """Update session configuration with language-specific instructions"""
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

        logger.debug('⚙️  Session instructions: %s', instructions)
        logger.debug('⚙️  Transcription prompt: %s', transcription_prompt)

        await self.websocket.send(json.dumps(session_config))

    def _listen(self):
        """Start audio capture with handler"""
        def audio_callback(indata, _frames, _time, status):
            if status:
                logger.warning("⚠️  Audio device status: %s", status)
            if self.is_active:
                self.audio_queue.put(indata.astype(np.int16))

        blocksize = int(CONFIG['openai']['sample_rate'] * CONFIG['openai']['chunk_duration_ms'] / 1000)

        AUDIO.start_recording(
            sample_rate=CONFIG['openai']['sample_rate'],
            dtype='int16',
            blocksize=blocksize,
            callback=audio_callback,
            input_gain=CONFIG['openai']['input_gain']
        )

    async def _send_audio(self):
        """Process audio from queue and send"""
        while self.is_active:
            if not self.audio_queue.empty():
                try:
                    audio_data = self.audio_queue.get_nowait()
                    b64_chunk = base64.b64encode(audio_data.tobytes()).decode('utf-8')
                    message = {"type": "input_audio_buffer.append", "audio": b64_chunk}
                    await self.websocket.send(json.dumps(message))
                except queue.Empty:
                    pass
            # Yield to event loop
            await asyncio.sleep(0.01)

    async def _play_response(self):
        """Play collected audio response and optionally wait for completion"""
        if self.response_chunks:
            combined_audio = b''.join(self.response_chunks)
            logger.info("🔊 Response playback started")
            AUDIO.start_playing(combined_audio, CONFIG['openai']['sample_rate'])

            async def playback_completion():
                while AUDIO.is_playing():
                    await asyncio.sleep(0.1)  # Poll every 100ms
                if self.display:
                    self.display.set_speaking(False)
                logger.info("🔊 Response playback finished")

            # For greeting + goodbye, await playback completion before continuing
            if self.is_greeting or self.is_terminating:
                await playback_completion()
            else:
                asyncio.create_task(playback_completion())

    def _is_sleep_word(self, text, threshold=85):
        """Check if text contains a sleep word using fuzzy matching"""
        sleep_word = self.lang_config['sleep_word'].lower()
        if not text or not sleep_word:
            return False

        filtered_text = re.sub(r'[,.!?]', '', text.strip().lower())
        score = fuzz.ratio(sleep_word, filtered_text)
        if score >= threshold:
            logger.debug("✅ Sleep word fuzzy matched: '%s' (score: %s)", sleep_word, score)
            return True
        return False

    async def _handle_message(self, data):
        """Handle incoming message from OpenAI"""
        Result = self.Result
        event_type = data.get("type")

        # Quieter debug logging
        if event_type not in {"response.output_audio.delta", "response.output_audio_transcript.delta"}:
            logger.debug("💬 Received message: %s", event_type)

        match event_type:
            case "input_audio_buffer.speech_started":
                logger.info("🔊 VAD: user speech started")

                # User is speaking; interrupt any ongoing response
                AUDIO.stop_playing()
                self.response_chunks.clear()

                # Stop speaking animation when interrupted
                if self.display:
                    self.display.set_speaking(False)

            case "input_audio_buffer.speech_stopped":
                logger.info("🔊 VAD: user speech ended")

                AUDIO.start_playing(CONFIG['sounds']['sent'])

            case "conversation.item.input_audio_transcription.completed":
                transcript = data.get("transcript", "")
                logger.info("🗣️  You said: %s", transcript)

                if self.display:
                    self.display.add_transcript("user", transcript)

                # Check for sleep words using fuzzy matching
                if self._is_sleep_word(transcript, CONFIG['session']['sleep_word_threshold']):
                    logger.info("💤 Sleep word detected: '%s'", transcript)
                    self.is_terminating = True

                    # Goodbye response already played; terminate session
                    if not self.response_chunks:
                        logger.debug("👋 Goodbye already played, terminating")
                        AUDIO.stop_recording()
                        return Result.GOODBYE

            case "response.output_audio.delta":
                if audio_base64 := data.get("delta", ""):
                    audio_bytes = base64.b64decode(audio_base64)
                    self.response_chunks.append(audio_bytes)

            case "response.output_audio_transcript.done":
                transcript = data.get("transcript", "")
                logger.info("🤖 Choco says: %s", transcript)

                if self.display:
                    self.display.add_transcript("choco", transcript)

            case "response.done":
                if self.display:
                    self.display.set_speaking(True)

                await self._play_response()
                self.response_chunks.clear()

                if self.is_greeting:
                    return Result.GREETED
                if self.is_terminating:
                    AUDIO.stop_recording()
                    return Result.GOODBYE

            case "error":
                logger.error("❌ OpenAI API Error: %s", data)
                self.is_active = False
                AUDIO.stop_recording()
                return Result.ERROR

        return None

    async def run(self):
        """Run conversation session"""
        Result = self.Result
        upload_task = None

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
                        logger.info("👂 Choco is listening...")
                        self._listen()  # Start recording synchronously
                        upload_task = asyncio.create_task(self._send_audio())
                        continue

                    # Handle exit conditions
                    if result in {Result.GOODBYE, Result.ERROR}:
                        self.is_active = False
                        break

                except asyncio.TimeoutError:
                    if self.is_greeting:
                        logger.error("⚠️  Timeout waiting for greeting response")
                    else:
                        logger.error("⏲️  Session timeout reached (%ss of inactivity)", timeout)
                    self.is_active = False
                    break

        except Exception as e:
            logger.error("⚠️  Error during conversation: %s", e)
        finally:
            AUDIO.stop_recording()
            if upload_task:
                upload_task.cancel()
            if self.websocket:
                await self.websocket.close()
