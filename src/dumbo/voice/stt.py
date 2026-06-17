from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class FasterWhisperStt:
    model_name: str
    device: str = "auto"
    compute_type: str = "auto"
    _model: object | None = None

    def _load(self) -> object:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper is not installed. Install Dumbo with .[voice]."
                ) from exc
            self._model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type
            )
        return self._model

    def transcribe_file(self, path: Path) -> str:
        model = self._load()
        segments, _info = model.transcribe(str(path))  # type: ignore[attr-defined]
        return " ".join(segment.text.strip() for segment in segments).strip()
