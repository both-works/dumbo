from __future__ import annotations

from dumbo.voice.tts import PiperTts


class Speaker:
    def __init__(self, tts: PiperTts):
        self.tts = tts

    def say(self, text: str) -> None:
        self.tts.speak(text)
