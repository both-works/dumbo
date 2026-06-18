from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from dumbo.agent.approval import ApprovalCallback, ApprovalMode, ApprovalRequest
from dumbo.agent.loop import AgentLoop
from dumbo.config import VoiceConfig
from dumbo.voice.microphone import record_fixed_seconds
from dumbo.voice.stt import FasterWhisperStt
from dumbo.voice.tts import PiperTts
from dumbo.voice.volume import set_system_volume_percent

Recorder = Callable[..., Path]
VolumeController = Callable[[int], None]
InputFunc = Callable[[str], str]
OutputFunc = Callable[[str], None]

STOP_PHRASES = {
    "quit",
    "exit",
    "stop",
    "stop listening",
    "go quiet",
    "goodbye",
    "goodbye dumbo",
    "dumbo stop",
    "jarvis stop",
}
YES_WORDS = {"y", "yes", "yeah", "yep", "approve", "approved", "do it", "go ahead", "confirm"}
NO_WORDS = {"n", "no", "nope", "cancel", "stop", "deny", "do not", "don't"}


@dataclass(frozen=True)
class VoiceTurnResult:
    raw_text: str
    command_text: str
    final_text: str
    stopped: bool = False


def run_voice_command_loop(
    agent: AgentLoop,
    voice: VoiceConfig,
    cache_dir: Path,
    *,
    recorder: Recorder = record_fixed_seconds,
    input_func: InputFunc = input,
    output_func: OutputFunc = print,
) -> str:
    if not voice.enabled:
        return (
            "Voice is disabled in config. Set voice.enabled=true after installing local voice "
            "dependencies."
        )

    stt = FasterWhisperStt(voice.stt_model)
    tts = PiperTts(Path(voice.tts_voice) if voice.tts_voice else None)
    speaker = _Speaker(tts, enabled=voice.tts_enabled, output_func=output_func)
    approval_callback = build_voice_approval_callback(
        stt=stt,
        voice=voice,
        cache_dir=cache_dir,
        recorder=recorder,
        speaker=speaker,
        input_func=input_func,
        output_func=output_func,
    )

    output_func(
        "Dumbo voice. Press Enter and speak naturally, type a fallback command, "
        "or say 'stop listening' to quit."
    )
    while True:
        typed = input_func("voice> ").strip()
        if typed:
            raw_text = typed
        else:
            raw_text = transcribe_fixed_window(
                stt,
                voice,
                cache_dir,
                seconds=voice.record_seconds,
                recorder=recorder,
            )
        result = run_voice_turn(
            agent,
            raw_text,
            voice,
            speaker=speaker,
            approval_callback=approval_callback,
        )
        if not result.raw_text:
            output_func("I didn't catch that.")
            continue
        output_func(f"You: {result.command_text or result.raw_text}")
        output_func(f"Dumbo: {result.final_text}")
        if result.stopped:
            return "Voice loop stopped."


def run_enter_to_record_voice_loop(
    agent: AgentLoop,
    voice: VoiceConfig,
    cache_dir: Path,
    recorder: Recorder = record_fixed_seconds,
) -> str:
    return run_voice_command_loop(agent, voice, cache_dir, recorder=recorder)


def run_voice_turn(
    agent: AgentLoop,
    raw_text: str,
    voice: VoiceConfig,
    *,
    speaker: _Speaker | None = None,
    approval_callback: ApprovalCallback | None = None,
) -> VoiceTurnResult:
    command = normalise_spoken_command(raw_text, wake_words=voice.wake_words)
    if not command:
        return VoiceTurnResult(raw_text=raw_text, command_text="", final_text="No speech detected.")
    if is_stop_command(command):
        final_text = "Voice loop stopped."
        if speaker is not None:
            speaker.say(final_text)
        return VoiceTurnResult(raw_text, command, final_text, stopped=True)

    response = agent.run(
        command,
        approval_mode=ApprovalMode.INTERACTIVE,
        approval_callback=approval_callback,
    )
    final_text = response.final_text.strip()
    if speaker is not None:
        speaker.say(final_text)
    return VoiceTurnResult(raw_text, command, final_text)


def build_voice_approval_callback(
    *,
    stt: FasterWhisperStt,
    voice: VoiceConfig,
    cache_dir: Path,
    recorder: Recorder,
    speaker: _Speaker,
    input_func: InputFunc,
    output_func: OutputFunc,
) -> ApprovalCallback:
    def approve(request: ApprovalRequest) -> bool:
        prompt = f"Approval needed: {request.expected_impact}. Risk: {request.risk_level.value}."
        output_func(prompt)
        speaker.say("Approval needed. Say yes or no, or type your answer.")
        typed = input_func("Approve? [y/N, Enter to answer by voice]: ").strip()
        if typed:
            return parse_spoken_confirmation(typed) is True
        spoken = transcribe_fixed_window(
            stt,
            voice,
            cache_dir,
            seconds=voice.confirmation_seconds,
            recorder=recorder,
        )
        output_func(f"Approval heard: {spoken or '[silence]'}")
        return parse_spoken_confirmation(spoken) is True

    return approve


def transcribe_fixed_window(
    stt: FasterWhisperStt,
    voice: VoiceConfig,
    cache_dir: Path,
    *,
    seconds: float | None = None,
    recorder: Recorder = record_fixed_seconds,
    volume_controller: VolumeController = set_system_volume_percent,
) -> str:
    if voice.lower_system_volume_on_record:
        volume_controller(voice.recording_volume_percent)
    audio_path = recorder(
        seconds=seconds or voice.record_seconds,
        save_audio=voice.save_audio,
        cache_dir=cache_dir,
    )
    try:
        return stt.transcribe_file(audio_path)
    finally:
        if not voice.save_audio:
            audio_path.unlink(missing_ok=True)


def normalise_spoken_command(raw_text: str, *, wake_words: tuple[str, ...]) -> str:
    text = " ".join(raw_text.strip().split())
    if not text:
        return ""
    text = text.strip(" .,!?:;\"'")
    text = _strip_wake_word(text, wake_words)
    text = re.sub(
        r"^(?:please|can you|could you|would you|will you|i need you to|i want you to)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+(?:please|thanks|thank you)$", "", text, flags=re.IGNORECASE)
    return text.strip(" .,!?:;\"'")


def is_stop_command(command: str) -> bool:
    return normalise_for_confirmation(command) in STOP_PHRASES


def parse_spoken_confirmation(text: str) -> bool | None:
    normalized = normalise_for_confirmation(text)
    if normalized in NO_WORDS:
        return False
    if re.search(r"\b(no|nope|cancel|deny|do not|don't)\b", normalized):
        return False
    if normalized in YES_WORDS:
        return True
    if re.search(r"\b(yes|yeah|yep|approve|approved|confirm|go ahead|do it)\b", normalized):
        return True
    return None


def normalise_for_confirmation(text: str) -> str:
    normalized = text.casefold().strip()
    normalized = re.sub(r"[^a-z0-9']+", " ", normalized)
    return " ".join(normalized.split())


def _strip_wake_word(text: str, wake_words: tuple[str, ...]) -> str:
    cleaned = text
    for wake_word in wake_words:
        word = re.escape(wake_word.strip())
        if not word:
            continue
        cleaned = re.sub(
            rf"^(?:hey\s+)?{word}[,\s]+",
            "",
            cleaned,
            count=1,
            flags=re.IGNORECASE,
        )
    return cleaned.strip()


class _Speaker:
    def __init__(self, tts: PiperTts, *, enabled: bool, output_func: OutputFunc):
        self._tts = tts
        self._enabled = enabled
        self._output = output_func
        self._failed = False

    def say(self, text: str) -> None:
        if not self._enabled or self._failed or not text:
            return
        try:
            self._tts.speak(text)
        except RuntimeError as exc:
            self._failed = True
            self._output(f"TTS unavailable: {exc}")
