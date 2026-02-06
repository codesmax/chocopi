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
from chocopi.language import detect_language_code
from chocopi.memory import (
    build_memory_block,
    load_memory,
    save_memory,
    summarize_session,
    update_memory,
)

logger = logging.getLogger(__name__)


class ConversationSession:
    """Conversation session with OpenAI Realtime API"""

    class Result(Enum):
        """Result codes for message handling"""
        GREETED = "greeted"
        GOODBYE = "goodbye"
        ERROR = "error"

    def __init__(self, learning_language='ko', profile=None, display=None):
        if profile is None:
            raise ValueError("ConversationSession requires a profile configuration")
        self.openai = CONFIG["openai"]
        self.session_config = CONFIG["session"]
        self.profile = profile
        self.profile_name = self.profile.get("name", "default").lower()
        self.memory = load_memory(self.profile_name)
        self.lang_config = CONFIG["languages"][learning_language]
        self.comprehension_age = self.profile["learning_languages"][learning_language]["comprehension_age"]
        self.websocket = None
        self.response_chunks = []
        self.audio_queue = queue.Queue()
        self.display = display
        self.is_active = True
        self.is_greeting = True
        self.is_terminating = False
        self.is_response_pending = False
        self.native_lang_code = self.profile["native_language"].lower()
        self.instruction_params = {
            "user_age": self.profile["user_age"],
            "native_language": CONFIG["languages"][self.profile["native_language"]]["language_name"],
            "learning_language": self.lang_config['language_name'],
            "comprehension_age": self.comprehension_age,
            "sleep_word": self.lang_config['sleep_word']
        }
        self.last_user_transcript = ""
        self.last_assistant_transcript = ""
        self.transcript_log = []

    async def connect(self):
        """Connect to OpenAI Realtime API"""
        logger.info("🌐 Establishing connnection to Realtime API...")
        openai_key = os.getenv('OPENAI_API_KEY')
        if not openai_key:
            raise ValueError("OPENAI_API_KEY environment variable not set. Please add it to your .env file.")
        try:
            headers = {"Authorization": f"Bearer {openai_key}"}
            uri = f"wss://api.openai.com/v1/realtime?model={self.openai['model']}"
            self.websocket = await websockets.connect(uri, additional_headers=headers)

            # Send session config
            await self._update_session()

            # Create and send greeting response to initiate conversation
            greeting_instructions = CONFIG['prompts']['greeting'].format(**self.instruction_params)
            await self._create_response(greeting_instructions)
        except Exception as e:
            logger.error("❌ Failed to connect to OpenAI API: %s", e)
            raise

    async def _update_session(self):
        """Update session configuration with language-specific instructions"""
        memory_block = build_memory_block(self.memory)
        instruction_params = self.instruction_params | {"memory_block": memory_block}
        session_instructions = CONFIG['prompts']['session'].format(**instruction_params)
        transcription_instructions = CONFIG['prompts']['transcription'].format(**self.instruction_params)

        session_config = CONFIG["openai"]["requests"]["session"].copy()
        session_config['session']['instructions'] = session_instructions
        session_config['session']['audio']['input']['transcription']['prompt'] = transcription_instructions

        logger.debug('⚙️  Session instructions: %s', session_instructions)
        logger.debug('⚙️  Transcription instructions: %s', transcription_instructions)

        await self.websocket.send(json.dumps(session_config))

    async def _create_response(self, instructions, transcript=None):
        """Create response with given instructions and optional transcript"""
        if transcript:
            message = CONFIG["openai"]["requests"]["user_message"].copy()
            message['item']['content'][0]['text'] = transcript
            await self.websocket.send(json.dumps(message))

        response_config = CONFIG["openai"]["requests"]["response"].copy()
        response_config['response']['instructions'] = instructions
        
        logger.debug('⚙️  Response instructions: %s', instructions)

        await self.websocket.send(json.dumps(response_config))

    def _listen(self):
        """Start audio capture with handler"""
        blocksize = int(self.openai['sample_rate'] * self.openai['chunk_duration_ms'] / 1000)

        def audio_callback(indata, _frames, _time, status):
            if status:
                logger.warning("⚠️  Audio device status: %s", status)
            if self.is_active:
                try:
                    self.audio_queue.put_nowait(indata)
                except queue.Full:
                    # Drop frame if uploads fall behind
                    logger.warning("⚠️  Audio queue full, dropping frame")
                    pass

        AUDIO.start_recording(
            sample_rate=self.openai['sample_rate'],
            dtype='int16',
            blocksize=blocksize,
            callback=audio_callback,
            input_gain=self.openai['input_gain']
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
            AUDIO.start_playing(combined_audio, self.openai['sample_rate'])

            async def playback_completion():
                while AUDIO.is_playing():
                    await asyncio.sleep(0.1)  # Poll every 100ms
                if self.display:
                    self.display.set_speaking(False)
                self.response_chunks.clear()
                logger.info("🔊 Response playback finished")

            # For greeting + goodbye, await playback completion before continuing
            if self.is_greeting or self.is_terminating:
                await playback_completion()
            else:
                asyncio.create_task(playback_completion())

    def _is_sleep_word(self, text, threshold=80):
        """Check if text contains a sleep word using fuzzy matching"""
        sleep_word = self.lang_config['sleep_word'].lower()
        if not text or not sleep_word:
            return False

        filtered_text = re.sub(r'[,.!?]', '', text.strip().lower())
        score = fuzz.partial_ratio(sleep_word, filtered_text)
        if score >= threshold:
            logger.debug("✅ Sleep word fuzzy matched: '%s' (score: %s)", sleep_word, score)
            return True
        return False

    def _on_response_created(self):
        self.is_response_pending = True

    def _on_speech_started(self):
        logger.info("🔊 VAD: user speech started")
        AUDIO.stop_playing()
        if self.display:
            self.display.set_speaking(False)

    def _on_speech_stopped(self):
        logger.info("🔊 VAD: user speech ended")
        AUDIO.start_playing(CONFIG["sounds"]["sent"])

    async def _on_transcription_completed(self, data):
        transcript = data.get("transcript", "")
        self._record_transcript("user", transcript, "🗣️  You said: %s", "user")
        response_instructions = self._build_response_instructions(transcript)

        await self._create_response(response_instructions, transcript)

    def _on_output_audio_delta(self, data):
        if audio_base64 := data.get("delta", ""):
            audio_bytes = base64.b64decode(audio_base64)
            self.response_chunks.append(audio_bytes)

    def _on_output_transcript_done(self, data):
        transcript = data.get("transcript", "")
        self._record_transcript("assistant", transcript, "🤖 Choco says: %s", "choco")

    async def _on_response_done(self):
        self.is_response_pending = False
        if self.display:
            self.display.set_speaking(True)

        await self._play_response()

        if self.is_greeting:
            return self.Result.GREETED
        if self.is_terminating:
            AUDIO.stop_recording()
            return self.Result.GOODBYE
        return None

    def _on_error(self, data):
        logger.error("❌ OpenAI API Error: %s", data)
        self.is_active = False
        AUDIO.stop_recording()
        return self.Result.ERROR

    async def _handle_message(self, data):
        """Handle incoming message from OpenAI"""
        Result = self.Result
        event_type = data.get("type")

        # Quieter debug logging
        if event_type not in {"response.output_audio.delta", "response.output_audio_transcript.delta"}:
            logger.debug("💬 Received message: %s", event_type)

        match event_type:
            case "response.created":
                self._on_response_created()
            case "input_audio_buffer.speech_started":
                self._on_speech_started()
            case "input_audio_buffer.speech_stopped":
                self._on_speech_stopped()
            case "conversation.item.input_audio_transcription.completed":
                await self._on_transcription_completed(data)
            case "response.output_audio.delta":
                self._on_output_audio_delta(data)
            case "response.output_audio_transcript.done":
                self._on_output_transcript_done(data)
            case "response.done":
                return await self._on_response_done()
            case "error":
                return self._on_error(data)

        return None

    def _record_transcript(self, role, transcript, log_format, display_role):
        logger.info(log_format, transcript)
        if role == "user":
            self.last_user_transcript = transcript
        else:
            self.last_assistant_transcript = transcript
        if transcript:
            self.transcript_log.append({"role": role, "text": transcript})
        if self.display:
            self.display.add_transcript(display_role, transcript)

    def _build_response_instructions(self, transcript):
        is_sleep_word = self._is_sleep_word(transcript, self.session_config['sleep_word_threshold'])
        if is_sleep_word:
            logger.info("💤 Sleep word detected: '%s'", transcript)
            self.is_terminating = True
            return CONFIG["prompts"]["goodbye"].format(**self.instruction_params)

        detected_language = detect_language_code(transcript)
        logger.debug("🔎 Detected language: %s", detected_language)
        translation_required = detected_language == self.native_lang_code
        native_language = CONFIG["languages"][self.profile["native_language"]]["language_name"]
        instruction_params = self.instruction_params | {
            "translation_instruction": f"- Add a full translation of your response to {native_language}" if translation_required else "",
        }
        return CONFIG["prompts"]["response"].format(**instruction_params)

    async def run(self):
        """Run conversation session"""
        Result = self.Result
        upload_task = None

        try:
            await self.connect()
            while self.is_active:
                try:
                    # Short timeout for greeting, normal timeout for conversation
                    timeout = self.session_config['greeting_timeout'] if self.is_greeting else self.session_config['conversation_timeout']
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
            if self.transcript_log:
                try:
                    self.memory = await asyncio.to_thread(
                        summarize_session,
                        self.profile_name,
                        self.profile,
                        self.transcript_log,
                        self.memory,
                    )
                except Exception as exc:
                    logger.warning("Memory summarization error: %s", exc)
                    update_memory(self.memory, self.last_user_transcript, self.last_assistant_transcript)
            else:
                update_memory(self.memory, self.last_user_transcript, self.last_assistant_transcript)
            save_memory(self.profile_name, self.memory)
            AUDIO.stop_recording()
            if upload_task:
                upload_task.cancel()
                try:
                    await upload_task
                except asyncio.CancelledError:
                    pass
            if self.websocket:
                await self.websocket.close()
