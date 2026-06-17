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
        if exe is None:
            raise RuntimeError("Piper executable was not found on PATH.")
        if self.voice_path is None or not self.voice_path.exists():
            raise RuntimeError("A Piper voice model path must be configured before speech output.")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav:
            wav_path = Path(wav.name)
        command = [exe, "--model", str(self.voice_path), "--output_file", str(wav_path)]
        subprocess.run(command, input=text, text=True, check=True)
        _play_wav(wav_path)


def _play_wav(path: Path) -> None:
    try:
        import winsound
    except ImportError as exc:
        raise RuntimeError(
            "WAV playback fallback is currently implemented only on Windows."
        ) from exc
    winsound.PlaySound(str(path), winsound.SND_FILENAME)
