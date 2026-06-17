from __future__ import annotations

from dataclasses import dataclass

from dumbo.agent.ollama_client import OllamaClient


@dataclass(frozen=True)
class EmbeddingResult:
    model: str
    vector: list[float]


class OllamaEmbeddingClient:
    def __init__(self, ollama: OllamaClient, model: str):
        self.ollama = ollama
        self.model = model

    def embed(self, text: str) -> EmbeddingResult:
        return EmbeddingResult(model=self.model, vector=self.ollama.embed(self.model, text))
