from __future__ import annotations


class VoiceActivityDetector:
    def __init__(self, aggressiveness: int = 2):
        try:
            import webrtcvad
        except ImportError as exc:
            raise RuntimeError("webrtcvad is not installed. Install Dumbo with .[voice].") from exc
        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        return bool(self._vad.is_speech(frame, sample_rate))
