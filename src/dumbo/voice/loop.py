from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dumbo.agent.loop import AgentLoop
from dumbo.config import VoiceConfig
from dumbo.voice.microphone import record_fixed_seconds
from dumbo.voice.stt import FasterWhisperStt
from dumbo.voice.tts import PiperTts

Recorder = Callable[..., Path]


def run_enter_to_record_voice_loop(
    agent: AgentLoop, voice: VoiceConfig, cache_dir: Path, recorder: Recorder = record_fixed_seconds
) -> str:
    if not voice.enabled:
        return (
            "Voice is disabled in config. Set voice.enabled=true after installing local voice "
            "dependencies. The MVP records a fixed five-second window after Enter."
        )
    stt = FasterWhisperStt(voice.stt_model)
    tts = PiperTts(Path(voice.tts_voice) if voice.tts_voice else None)
    print("Press Enter to record a fixed five-second window, or type q to quit.")
    while True:
        command = input("> ")
        if command.strip().casefold() == "q":
            return "Voice loop stopped."
        text = transcribe_fixed_window(stt, voice, cache_dir, recorder=recorder)
        if not text:
            print("No speech detected.")
            continue
        print(f"You: {text}")
        response = agent.run(text)
        print(f"Dumbo: {response.final_text}")
        try:
            tts.speak(response.final_text)
        except RuntimeError as exc:
            print(f"TTS unavailable: {exc}")


def transcribe_fixed_window(
    stt: FasterWhisperStt,
    voice: VoiceConfig,
    cache_dir: Path,
    *,
    recorder: Recorder = record_fixed_seconds,
) -> str:
    audio_path = recorder(save_audio=voice.save_audio, cache_dir=cache_dir)
    try:
        return stt.transcribe_file(audio_path)
    finally:
        if not voice.save_audio:
            audio_path.unlink(missing_ok=True)
