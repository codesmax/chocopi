"""Conversation session powered by Pipecat"""
import asyncio
import logging
import re
import time

from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    EndFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMRunFrame,
    LLMTextFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
    InputAudioRawFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from rapidfuzz import fuzz

from chocopi.audio import AUDIO
from chocopi.config import CONFIG, PROVIDER
from chocopi.language import detect_language_code
from chocopi.memory import (
    build_memory_block,
    load_memory,
    save_memory,
    summarize_session,
    update_memory,
)
from chocopi.providers import create_llm_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline processor
# ---------------------------------------------------------------------------

class ChocoPiProcessor(FrameProcessor):
    """
    Handles ChocoPi-specific logic as a Pipecat pipeline processor.

    Response flow:
    - UserStoppedSpeakingFrame  → logged (alert sound moved to _on_transcript for all-provider consistency)
    - TranscriptionFrame        → play alert sound, log, detect echo/sleep, detect language, trigger _respond()
    - LLMFullResponseEndFrame   → log assistant transcript; handle termination sequence
    - BotStoppedSpeakingFrame   → stop display animation (travels UPSTREAM, not filtered by direction)
    """

    def __init__(self, session: "ConversationSession"):
        super().__init__()
        self._s = session
        self._task: PipelineTask | None = None
        self._assistant_text_buf: list[str] = []
        self._is_responding = False   # guard against double response.create
        self._goodbye_sent = False    # two-stage termination: goodbye → EndFrame

    def set_task(self, task: PipelineTask) -> None:
        self._task = task

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)

        if not isinstance(frame, InputAudioRawFrame):
            logger.debug("🔄 Processing frame: %s (direction: %s)", type(frame).__name__, direction)

        # BotStoppedSpeakingFrame travels UPSTREAM from output transport — handle
        # it outside the DOWNSTREAM guard so animation stops when audio finishes.
        if isinstance(frame, BotStoppedSpeakingFrame):
            if self._s.display:
                self._s.display.set_speaking(False)
        elif direction == FrameDirection.DOWNSTREAM:
            match frame:
                case UserStoppedSpeakingFrame():
                    logger.debug("👂 Detected user stopped speaking")
                    # alert sound plays in _on_transcript once transcript arrives

                case LLMFullResponseStartFrame():
                    # Don't stop alert sound here — LLMFullResponseStartFrame fires
                    # the instant response.create is sent, not when audio arrives.
                    # sent.wav is short enough to complete on its own before playback starts.
                    self._is_responding = True
                    if self._s.display:
                        self._s.display.set_speaking(True)

                case TranscriptionFrame():
                    await self._on_transcript(frame.text)

                case LLMTextFrame():
                    self._assistant_text_buf.append(frame.text)

                case LLMFullResponseEndFrame():
                    self._is_responding = False
                    await self._on_response_done()

        await self.push_frame(frame, direction)

    async def _respond(self, instructions: str | None = None) -> None:
        """Trigger a response with the given per-response instructions."""
        s = self._s
        s._set_response_instructions(instructions or s._default_response_instructions)
        await self._task.queue_frames([LLMRunFrame()])

    async def _on_transcript(self, transcript: str):
        s = self._s
        s._record_transcript("user", transcript, "🗣️  You said: %s", "user")

        if s.is_greeting:
            return

        AUDIO.start_playing(CONFIG["sounds"]["sent"])

        # Echo detection
        echo_cfg = s.session_config.get("echo_detection", {})
        if s._is_echo(transcript):
            s._consecutive_echo_turns += 1
            logger.debug(
                "🔁 Echo candidate (%d/%d): '%s'",
                s._consecutive_echo_turns, echo_cfg.get("consecutive_limit", 5), transcript,
            )
            if s._consecutive_echo_turns >= echo_cfg.get("consecutive_limit", 5):
                logger.warning("🔁 Echo loop detected after %d turns", s._consecutive_echo_turns)
                s.is_terminating = True
        else:
            s._consecutive_echo_turns = 0

        # Sleep word detection
        if not s.is_terminating and s._is_sleep_word(transcript, s.session_config["sleep_word_threshold"]):
            logger.info("💤 Sleep word detected: '%s'", transcript)
            s.is_terminating = True

        # Language detection → compute instructions for this turn
        instructions = s._default_response_instructions
        if not s.is_terminating:
            detected_language = detect_language_code(transcript)
            logger.debug("🔎 Detected language: %s", detected_language)
            if detected_language == s.native_lang_code:
                native_language = CONFIG["languages"][s.profile["native_language"]]["language_name"]
                translation_prompt = f"- Add a translation of your full response to {native_language}"
            else:
                translation_prompt = ""
            instructions = s._build_response_instructions(translation_prompt)

        if not self._is_responding:
            await self._respond(instructions)

    async def _on_response_done(self):
        s = self._s
        transcript = "".join(self._assistant_text_buf).strip()
        self._assistant_text_buf.clear()
        s._record_transcript("assistant", transcript, "🤖 Choco says: %s", "choco")

        if s.is_greeting:
            s.is_greeting = False
            s.session_start_time = time.monotonic()
            logger.info("👂 Choco is listening...")
            return

        if s.is_terminating:
            if not self._goodbye_sent:
                self._goodbye_sent = True
                await self._respond(s._build_goodbye_instructions())
            else:
                await self._task.queue_frames([EndFrame()])


# ---------------------------------------------------------------------------
# Conversation session
# ---------------------------------------------------------------------------

class ConversationSession:
    """Conversation session backed by a Pipecat voice LLM pipeline."""

    def __init__(self, learning_language="ko", profile=None, display=None):
        if profile is None:
            raise ValueError("ConversationSession requires a profile configuration")

        provider_config = CONFIG["providers"][PROVIDER]

        self.session_config = CONFIG["session"]
        self.profile = profile
        self.profile_name = profile.get("name", "default").lower()
        self.memory = load_memory(self.profile_name)
        self.lang_config = CONFIG["languages"][learning_language]
        self.comprehension_age = profile["learning_languages"][learning_language]["comprehension_age"]
        self.display = display

        self.is_greeting = True
        self.is_terminating = False
        self.native_lang_code = profile["native_language"].lower()
        self.instruction_params = {
            "user_age": profile["user_age"],
            "native_language": CONFIG["languages"][profile["native_language"]]["language_name"],
            "learning_language": self.lang_config["language_name"],
            "comprehension_age": self.comprehension_age,
            "sleep_word": self.lang_config["sleep_word"],
        }

        self.last_user_transcript = ""
        self.last_assistant_transcript = ""
        self.transcript_log = []
        self.session_start_time = None
        self._consecutive_echo_turns = 0

        # Built once; used as the base for all per-response instruction strings
        memory_block = build_memory_block(self.memory)
        self._session_instructions = CONFIG["prompts"]["session"].format(
            **self.instruction_params, memory_block=memory_block
        )
        transcription_instructions = CONFIG["prompts"]["transcription"].format(
            **self.instruction_params
        )
        logger.debug("⚙️  Session instructions: %s", self._session_instructions)

        # Default response instructions (no translation)
        self._default_response_instructions = self._build_response_instructions("")

        self._greeting_instructions = CONFIG["prompts"]["greeting"].format(**self.instruction_params)
        self._llm_service, self._set_response_instructions = create_llm_service(
            PROVIDER, provider_config, self._session_instructions, transcription_instructions,
            greeting_instructions=self._greeting_instructions,
        )

    # --- Instruction builders ---

    def _build_response_instructions(self, translation_prompt: str) -> str:
        """Per-response instructions injected via ResponseProperties.instructions.

        The OpenAI Realtime API adds these to the session-level instructions (set once
        via session.update at startup) rather than replacing them, so we only need the
        per-turn response rules here — not the full session context.
        """
        return CONFIG["prompts"]["response"].format(
            **self.instruction_params, translation_prompt=translation_prompt
        )

    def _build_goodbye_instructions(self) -> str:
        return CONFIG["prompts"]["goodbye"].format(**self.instruction_params)

    # --- Transcript helpers ---

    def _is_echo(self, transcript: str) -> bool:
        echo_cfg = self.session_config.get("echo_detection", {})
        max_words = echo_cfg.get("max_words", 4)
        threshold = echo_cfg.get("overlap_threshold", 80)
        if not transcript or not self.last_assistant_transcript:
            return False
        if len(transcript.split()) > max_words:
            return False
        return fuzz.partial_ratio(transcript.lower(), self.last_assistant_transcript.lower()) >= threshold

    def _is_sleep_word(self, text: str, threshold: int = 80) -> bool:
        sleep_word = self.lang_config["sleep_word"].lower()
        if not text or not sleep_word:
            return False
        filtered = re.sub(r"[,.!?]", "", text.strip().lower())
        score = fuzz.partial_ratio(sleep_word, filtered)
        if score >= threshold:
            logger.debug("✅ Sleep word matched: '%s' (score: %d)", sleep_word, score)
            return True
        return False

    def _record_transcript(self, role: str, transcript: str, log_format: str, display_role: str):
        logger.info(log_format, transcript)
        if role == "user":
            self.last_user_transcript = transcript
        else:
            self.last_assistant_transcript = transcript
        if transcript:
            self.transcript_log.append({"role": role, "text": transcript})
        if self.display:
            self.display.add_transcript(display_role, transcript)

    # --- Main loop ---

    async def run(self):
        """Build and run the Pipecat pipeline for this conversation session."""
        transport = LocalAudioTransport(
            LocalAudioTransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
            )
        )

        chocopi_proc = ChocoPiProcessor(self)
        pipeline = Pipeline([transport.input(), self._llm_service, chocopi_proc, transport.output()])
        task = PipelineTask(pipeline)
        chocopi_proc.set_task(task)

        # Greeting: seed an empty LLMContext to trigger _handle_context → _create_initial_response.
        # For OpenAI: set_response_instructions injects the greeting into the next response.create.
        # For Gemini/Ultravox: greeting_instructions are baked into the system instruction at
        # factory time; _create_initial_response override handles the trigger directly.
        self._set_response_instructions(self._greeting_instructions)
        await task.queue_frames([LLMContextFrame(context=LLMContext())])

        try:
            runner = PipelineRunner(handle_sigint=False)
            await runner.run(task)
        except Exception as e:
            logger.error("⚠️  Error during conversation: %s", e)

    # --- Memory ---

    async def persist_memory(self):
        """Summarize and persist session memory."""
        memory = self.memory
        logger.info("🧠 Updating memory with latest conversation...")
        if self.transcript_log:
            try:
                memory = await asyncio.to_thread(
                    summarize_session,
                    self.profile_name,
                    self.profile,
                    self.transcript_log,
                    memory,
                )
            except Exception as exc:
                logger.warning("Memory summarization error: %s", exc)
                update_memory(memory, self.last_user_transcript, self.last_assistant_transcript)
        else:
            update_memory(memory, self.last_user_transcript, self.last_assistant_transcript)

        try:
            await asyncio.to_thread(save_memory, self.profile_name, memory)
            logger.info("💾 Memory saved successfully.")
        except Exception as exc:
            logger.warning("Memory save error: %s", exc)
            return
        self.memory = memory
