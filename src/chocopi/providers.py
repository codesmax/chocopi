"""Pipecat LLM service factories for each supported provider"""
import logging
import os

logger = logging.getLogger(__name__)


def create_llm_service(provider_name, provider_config, session_instructions, transcription_instructions=""):
    """
    Instantiate the Pipecat LLM service for the given provider.

    Returns (service, set_response_instructions_fn) where set_response_instructions_fn(str)
    stores per-response instructions injected into the next response trigger.
    """
    if provider_name == "openai_realtime":
        return _openai_realtime(provider_config, session_instructions, transcription_instructions)
    elif provider_name == "gemini_live":
        return _gemini_live(provider_config, session_instructions)
    elif provider_name == "ultravox":
        return _ultravox(provider_config, session_instructions)
    else:
        raise ValueError(f"Unknown provider: {provider_name!r}")


def _openai_realtime(config, session_instructions, transcription_instructions):
    """
    OpenAI Realtime API via Pipecat.

    Extends the base service with four additions:
    1. LLMRunFrame triggers _create_response() (manual response control)
    2. TranscriptionFrame re-pushed DOWNSTREAM so ChocoPiProcessor can observe it
       (base class pushes UPSTREAM only)
    3. send_client_event intercepts ResponseCreateEvent to inject per-response
       instructions, and patches SessionUpdateEvent to include create_response=False
       in server_vad turn_detection (Pipecat's TurnDetection model omits these fields,
       so they must be patched post-serialization)
    4. _truncate_current_audio_response is a no-op to prevent invalid_value server
       errors when Pipecat's byte count exceeds server's committed bytes on interruption
    """
    from pipecat.frames.frames import LLMRunFrame, TranscriptionFrame
    from pipecat.processors.frame_processor import FrameDirection
    from pipecat.services.openai.realtime.events import (
        AudioConfiguration,
        AudioInput,
        AudioOutput,
        InputAudioNoiseReduction,
        InputAudioTranscription,
        ResponseCreateEvent,
        SessionProperties,
        SessionUpdateEvent,
        TurnDetection,
    )
    from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService as _Base
    from pipecat.utils.time import time_now_iso8601

    class OpenAIRealtimeLLMService(_Base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._response_instructions: str | None = None

        async def process_frame(self, frame, direction):
            if isinstance(frame, LLMRunFrame):
                await self._create_response()
                return
            await super().process_frame(frame, direction)

        async def handle_evt_input_audio_transcription_completed(self, evt):
            await super().handle_evt_input_audio_transcription_completed(evt)
            await self.push_frame(
                TranscriptionFrame(evt.transcript, "", time_now_iso8601()),
                FrameDirection.DOWNSTREAM,
            )

        async def send_client_event(self, event):
            if isinstance(event, ResponseCreateEvent) and self._response_instructions:
                instructions, self._response_instructions = self._response_instructions, None
                event = event.model_copy(update={
                    "response": event.response.model_copy(
                        update={"instructions": instructions}
                    )
                })
            if isinstance(event, ResponseCreateEvent):
                logger.debug(
                    "📤 response.create instructions: %s",
                    event.response.instructions if event.response else None,
                )
                await super().send_client_event(event)
                return

            if isinstance(event, SessionUpdateEvent):
                # Pydantic's union validation on AudioInput.turn_detection coerces
                # TurnDetection to the base schema, dropping create_response and
                # interrupt_response. Patch the serialized dict before sending.
                data = event.model_dump(exclude_none=True)
                try:
                    td = data["session"]["audio"]["input"]["turn_detection"]
                    if isinstance(td, dict) and td.get("type") == "server_vad":
                        td["create_response"] = False
                        td["interrupt_response"] = True
                except (KeyError, TypeError) as e:
                    logger.warning("⚠️  Could not patch turn_detection in session.update: %s", e)
                logger.debug(
                    "📤 session.update turn_detection: %s",
                    data.get("session", {}).get("audio", {}).get("input", {}).get("turn_detection"),
                )
                await self._ws_send(data)
                return

            await super().send_client_event(event)

        async def _truncate_current_audio_response(self):
            self._current_audio_response = None

    pc = config
    td = pc.get("turn_detection", {})
    noise_red = pc.get("noise_reduction")

    service = OpenAIRealtimeLLMService(
        api_key=os.getenv(pc["api_key_env"]),
        settings=OpenAIRealtimeLLMService.Settings(
            model=pc["model"],
            system_instruction=session_instructions,
            session_properties=SessionProperties(
                audio=AudioConfiguration(
                    input=AudioInput(
                        transcription=InputAudioTranscription(
                            model=pc.get("transcription_model", "gpt-4o-mini-transcribe"),
                            prompt=transcription_instructions,
                        ),
                        noise_reduction=InputAudioNoiseReduction(type=noise_red) if noise_red else None,
                        turn_detection=TurnDetection(
                            threshold=td.get("threshold", 0.3),
                            prefix_padding_ms=td.get("prefix_padding_ms", 300),
                            silence_duration_ms=td.get("silence_duration_ms", 1200),
                        ) if td else None,
                    ),
                    output=AudioOutput(
                        voice=pc.get("voice", "alloy"),
                        speed=pc.get("output_speed", 1.0),
                    ),
                ),
            ),
        ),
    )

    def set_response_instructions(instructions: str):
        service._response_instructions = instructions

    return service, set_response_instructions


def _gemini_live(config, session_instructions):
    """
    Google Gemini Live API via Pipecat (pipecat-ai[google]).

    Per-response instruction injection is not available: Gemini Live's
    BidiGenerateContentSetup sets the system instruction once at session start with
    no per-response override channel equivalent to OpenAI's response.create.instructions.
    Dynamic per-turn rules (e.g. translation) should be expressed as standing conditional
    instructions in session_instructions so the model applies them on its own judgment.
    """
    from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService

    service = GeminiLiveLLMService(
        api_key=os.getenv(config["api_key_env"]),
        model=config.get("model", "gemini-2.0-flash-live"),
        settings=GeminiLiveLLMService.Settings(
            voice=config.get("voice", "Aoede"),
            system_instruction=session_instructions,
        ),
    )

    def set_response_instructions(instructions: str):
        pass

    return service, set_response_instructions


def _ultravox(config, session_instructions):
    """
    Ultravox Realtime API via Pipecat (pipecat-ai[ultravox]).

    Per-response instruction injection is not available via Pipecat's current service
    layer. Ultravox's call-stages API can update the system prompt mid-call, but that
    is not yet exposed by UltravoxRealtimeLLMService. Dynamic per-turn rules should be
    expressed as standing conditional instructions in session_instructions.
    """
    from pipecat.services.ultravox.llm import OneShotInputParams, UltravoxRealtimeLLMService

    service = UltravoxRealtimeLLMService(
        params=OneShotInputParams(
            api_key=os.getenv(config["api_key_env"]),
            system_prompt=session_instructions,
            voice=config.get("voice", "Mark"),
            model=config.get("model", "fixie-ai/ultravox-70B"),
        )
    )

    def set_response_instructions(instructions: str):
        pass

    return service, set_response_instructions
