from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dumbo.paths import repository_root, system_roots, user_default_roots


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str = "http://localhost:11434"
    request_timeout_seconds: int = 120
    pull_timeout_seconds: int = 3600


@dataclass(frozen=True)
class FilesystemConfig:
    project_roots: tuple[Path, ...] = ()
    allow_sensitive_reads: bool = False
    include_available_drives: bool = False


@dataclass(frozen=True)
class VoiceConfig:
    enabled: bool = False
    push_to_talk_key: str = "ctrl+space"
    stt_model: str = "small.en"
    tts_voice: str = ""
    tts_enabled: bool = True
    save_audio: bool = False
    record_seconds: float = 7.0
    confirmation_seconds: float = 3.0
    lower_system_volume_on_record: bool = True
    recording_volume_percent: int = 5
    wake_words: tuple[str, ...] = ("dumbo", "jarvis")


@dataclass(frozen=True)
class AppConfig:
    name: str = "Dumbo"
    profile: str = "recommended"
    trusted_mode: bool = False
    max_tool_calls_per_request: int = 8
    tool_timeout_seconds: int = 30
    enable_privileged_tools: bool = False
    app_aliases: dict[str, str] = field(default_factory=dict)
    allowed_executable_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class BrowserConfig:
    headless: bool = False
    trusted_local_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuditConfig:
    tail_limit: int = 20


@dataclass(frozen=True)
class ModelRuntimeConfig:
    context_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    repeat_penalty: float | None = None
    num_predict: int | None = None
    reasoning_effort: str = "high"


@dataclass(frozen=True)
class ModelProfile:
    name: str
    planner_model: str
    vision_model: str
    embedding_model: str
    stt_model: str
    tts_engine: str
    optional_planner_model: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def ollama_models(self) -> tuple[str, ...]:
        return (self.planner_model, self.vision_model, self.embedding_model)


@dataclass(frozen=True)
class DumboConfig:
    app: AppConfig = field(default_factory=AppConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    filesystem: FilesystemConfig = field(default_factory=FilesystemConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    model: ModelRuntimeConfig = field(default_factory=ModelRuntimeConfig)

    @property
    def allowed_roots(self) -> list[Path]:
        roots = [*user_default_roots(), *self.filesystem.project_roots]
        if self.filesystem.include_available_drives:
            roots.extend(system_roots())
        return roots


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return data


def _path_tuple(values: Any) -> tuple[Path, ...]:
    if values is None:
        return ()
    if not isinstance(values, list):
        raise ValueError("filesystem.project_roots must be a list")
    return tuple(Path(str(value)).expanduser().resolve() for value in values)


def _string_tuple(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list):
        raise ValueError("Expected a list of strings")
    return tuple(str(value) for value in values)


def load_config(config_path: Path | None = None) -> DumboConfig:
    root = repository_root()
    path = config_path or root / "config" / "default.yaml"
    data = _read_yaml(path) if path.exists() else {}

    app_data = data.get("app", {}) or {}
    ollama_data = data.get("ollama", {}) or {}
    filesystem_data = data.get("filesystem", {}) or {}
    voice_data = data.get("voice", {}) or {}
    browser_data = data.get("browser", {}) or {}
    audit_data = data.get("audit", {}) or {}
    model_data = data.get("model", {}) or {}
    app_aliases = app_data.pop("app_aliases", {}) or {}
    allowed_executable_paths = _path_tuple(app_data.pop("allowed_executable_paths", []))
    if not isinstance(app_aliases, dict):
        raise ValueError("app.app_aliases must be a mapping")

    return DumboConfig(
        app=AppConfig(
            **app_data,
            app_aliases={str(key).casefold(): str(value) for key, value in app_aliases.items()},
            allowed_executable_paths=allowed_executable_paths,
        ),
        ollama=OllamaConfig(**ollama_data),
        filesystem=FilesystemConfig(
            project_roots=_path_tuple(filesystem_data.get("project_roots", [])),
            allow_sensitive_reads=bool(filesystem_data.get("allow_sensitive_reads", False)),
            include_available_drives=bool(filesystem_data.get("include_available_drives", False)),
        ),
        voice=VoiceConfig(
            enabled=bool(voice_data.get("enabled", False)),
            push_to_talk_key=str(voice_data.get("push_to_talk_key", "ctrl+space")),
            stt_model=str(voice_data.get("stt_model", "small.en")),
            tts_voice=str(voice_data.get("tts_voice", "")),
            tts_enabled=bool(voice_data.get("tts_enabled", True)),
            save_audio=bool(voice_data.get("save_audio", False)),
            record_seconds=float(voice_data.get("record_seconds", 7.0)),
            confirmation_seconds=float(voice_data.get("confirmation_seconds", 3.0)),
            lower_system_volume_on_record=bool(
                voice_data.get("lower_system_volume_on_record", True)
            ),
            recording_volume_percent=int(voice_data.get("recording_volume_percent", 5)),
            wake_words=_string_tuple(voice_data.get("wake_words", ["dumbo", "jarvis"])),
        ),
        browser=BrowserConfig(
            headless=bool(browser_data.get("headless", False)),
            trusted_local_urls=_string_tuple(browser_data.get("trusted_local_urls", [])),
        ),
        audit=AuditConfig(**audit_data),
        model=ModelRuntimeConfig(**model_data),
    )


def load_model_profile(name: str, root: Path | None = None) -> ModelProfile:
    repo = root or repository_root()
    path = repo / "config" / "profiles" / f"{name}.yaml"
    data = _read_yaml(path)
    notes = data.pop("notes", []) or []
    return ModelProfile(notes=tuple(str(note) for note in notes), **data)


def list_model_profiles(root: Path | None = None) -> list[str]:
    repo = root or repository_root()
    profile_dir = repo / "config" / "profiles"
    if not profile_dir.exists():
        return []
    return sorted(path.stem for path in profile_dir.glob("*.yaml"))
