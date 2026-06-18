from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dumbo.agent.approval import ApprovalMode, ApprovalRequest
from dumbo.config import VoiceConfig
from dumbo.tools.base import RiskLevel, ToolResult
from dumbo.voice.loop import (
    build_voice_approval_callback,
    normalise_spoken_command,
    parse_spoken_confirmation,
    run_voice_turn,
    transcribe_fixed_window,
)


class FakeAgent:
    def __init__(self):
        self.commands: list[str] = []
        self.approval_modes: list[ApprovalMode] = []
        self.approval_callbacks = []

    def run(self, command: str, *, approval_mode, approval_callback=None):
        self.commands.append(command)
        self.approval_modes.append(approval_mode)
        self.approval_callbacks.append(approval_callback)
        return SimpleNamespace(final_text=f"done: {command}")


class FakeSpeaker:
    def __init__(self):
        self.spoken: list[str] = []

    def say(self, text: str) -> None:
        self.spoken.append(text)


class FakeStt:
    def __init__(self, text: str):
        self.text = text
        self.paths: list[Path] = []

    def transcribe_file(self, path: Path) -> str:
        self.paths.append(path)
        return self.text


def test_normalise_spoken_command_strips_wake_word_and_politeness() -> None:
    assert (
        normalise_spoken_command(
            "Hey Dumbo, could you open a word document please?",
            wake_words=("dumbo", "jarvis"),
        )
        == "open a word document"
    )
    assert (
        normalise_spoken_command("Jarvis open Chrome", wake_words=("dumbo", "jarvis"))
        == "open Chrome"
    )


def test_parse_spoken_confirmation() -> None:
    assert parse_spoken_confirmation("yes, go ahead") is True
    assert parse_spoken_confirmation("no cancel that") is False
    assert parse_spoken_confirmation("don't do it") is False
    assert parse_spoken_confirmation("do not approve") is False
    assert parse_spoken_confirmation("maybe later") is None


def test_run_voice_turn_executes_normalized_command_and_speaks() -> None:
    agent = FakeAgent()
    speaker = FakeSpeaker()

    result = run_voice_turn(
        agent,
        "Dumbo, open a word document.",
        VoiceConfig(enabled=True),
        speaker=speaker,
    )

    assert result.command_text == "open a word document"
    assert result.final_text == "done: open a word document"
    assert agent.commands == ["open a word document"]
    assert agent.approval_modes == [ApprovalMode.INTERACTIVE]
    assert speaker.spoken == ["done: open a word document"]


def test_run_voice_turn_stops_without_agent_call() -> None:
    agent = FakeAgent()
    result = run_voice_turn(agent, "Dumbo stop listening", VoiceConfig(enabled=True))

    assert result.stopped
    assert result.final_text == "Voice loop stopped."
    assert agent.commands == []


def test_voice_approval_callback_accepts_typed_yes(tmp_path: Path) -> None:
    speaker = FakeSpeaker()
    callback = build_voice_approval_callback(
        stt=FakeStt(""),
        voice=VoiceConfig(enabled=True),
        cache_dir=tmp_path,
        recorder=lambda **_: tmp_path / "unused.wav",
        speaker=speaker,
        input_func=lambda _prompt: "yes",
        output_func=lambda _message: None,
    )
    request = ApprovalRequest(
        tool_name="run_powershell",
        args={"command": "Get-ChildItem"},
        risk_level=RiskLevel.SHELL,
        policy_reason="Shell command requires explicit confirmation.",
        dry_run_result=ToolResult.success("Would run command."),
        expected_impact="Runs PowerShell Get-ChildItem",
        rollback_notes="No automatic rollback is available.",
    )

    assert callback(request) is True
    assert speaker.spoken


def test_transcribe_fixed_window_deletes_unsaved_audio(tmp_path: Path) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"wav")
    stt = FakeStt("hello")

    text = transcribe_fixed_window(
        stt,
        VoiceConfig(enabled=True, save_audio=False),
        tmp_path,
        seconds=2.5,
        recorder=lambda **kwargs: audio,
    )

    assert text == "hello"
    assert not audio.exists()
    assert stt.paths == [audio]
