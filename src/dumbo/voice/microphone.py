from __future__ import annotations

import tempfile
import wave
from datetime import UTC, datetime
from pathlib import Path


def record_fixed_seconds(
    seconds: float = 5.0,
    sample_rate: int = 16000,
    *,
    save_audio: bool = False,
    cache_dir: Path | None = None,
) -> Path:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError("sounddevice is not installed. Install Dumbo with .[voice].") from exc
    frames = int(seconds * sample_rate)
    audio = sd.rec(frames, samplerate=sample_rate, channels=1, dtype="int16")
    sd.wait()
    if save_audio:
        if cache_dir is None:
            raise RuntimeError("cache_dir is required when voice.save_audio=true.")
        audio_dir = cache_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        path = audio_dir / f"voice-{stamp}.wav"
    else:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = Path(handle.name)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(audio.tobytes())
    return path
