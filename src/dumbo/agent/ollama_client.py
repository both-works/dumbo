from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class OllamaError(RuntimeError):
    pass


@dataclass(frozen=True)
class OllamaClient:
    base_url: str = "http://localhost:11434"
    timeout_seconds: int = 120

    def tags(self) -> list[str]:
        payload = self._request("GET", "/api/tags")
        models = payload.get("models", [])
        return sorted(str(model.get("name")) for model in models if model.get("name"))

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        format_value: str | dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
        if tools is not None:
            body["tools"] = tools
        if format_value is not None:
            body["format"] = format_value
        if options:
            body["options"] = options
        return self._request("POST", "/api/chat", body)

    def embed(self, model: str, text: str) -> list[float]:
        body = {"model": model, "input": text}
        payload = self._request("POST", "/api/embed", body)
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list) and embeddings:
            return [float(value) for value in embeddings[0]]
        embedding = payload.get("embedding")
        if isinstance(embedding, list):
            return [float(value) for value in embedding]
        raise OllamaError("Ollama embedding response did not include a vector.")

    def pull(self, model: str) -> dict[str, Any]:
        return self._request("POST", "/api/pull", {"name": model, "stream": False})

    def version(self) -> str | None:
        try:
            payload = self._request("GET", "/api/version")
        except OllamaError:
            return None
        version = payload.get("version")
        return str(version) if version else None

    def is_available(self) -> tuple[bool, str]:
        try:
            self.tags()
        except OllamaError as exc:
            return False, str(exc)
        return True, "Ollama is reachable."

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = self.base_url.rstrip("/") + path
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise OllamaError(f"Ollama request failed for {url}: {exc}") from exc
        except TimeoutError as exc:
            raise OllamaError(f"Ollama request timed out for {url}") from exc
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Ollama returned invalid JSON for {url}") from exc
        if isinstance(payload, dict) and payload.get("error"):
            raise OllamaError(str(payload["error"]))
        if not isinstance(payload, dict):
            raise OllamaError(f"Ollama returned unexpected payload for {url}")
        return payload
