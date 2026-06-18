from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PiperTts:
    voice_path: Path | None = None
    executable: str = "piper"

    def speak(self, text: str) -> None:
        exe = shutil.which(self.executable)
        if exe is None or self.voice_path is None or not self.voice_path.exists():
            _speak_windows_sapi(text)
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav:
            wav_path = Path(wav.name)
        try:
            command = [exe, "--model", str(self.voice_path), "--output_file", str(wav_path)]
            subprocess.run(command, input=text, text=True, check=True)
            _play_wav(wav_path)
        finally:
            wav_path.unlink(missing_ok=True)


def _speak_windows_sapi(text: str) -> None:
    command = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        (
            "Add-Type -AssemblyName System.Speech; "
            "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$speaker.Rate = 0; "
            "$speaker.Speak([Console]::In.ReadToEnd())"
        ),
    ]
    completed = subprocess.run(
        command,
        input=text[:2000],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Piper is not configured and Windows speech synthesis failed: "
            f"{completed.stderr or completed.stdout}"
        )


def _play_wav(path: Path) -> None:
    try:
        import winsound
    except ImportError as exc:
        raise RuntimeError(
            "WAV playback fallback is currently implemented only on Windows."
        ) from exc
    winsound.PlaySound(str(path), winsound.SND_FILENAME)
