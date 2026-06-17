from __future__ import annotations

import ctypes
import json
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from dumbo.agent.ollama_client import OllamaClient
from dumbo.config import DumboConfig
from dumbo.paths import AppPaths


@dataclass(frozen=True)
class GpuInfo:
    name: str
    vram_mb: int | None = None
    source: str = "unknown"


@dataclass(frozen=True)
class HardwareInfo:
    os_name: str
    os_version: str
    python_version: str
    cpu: str
    ram_gb: float | None
    gpus: tuple[GpuInfo, ...] = ()


@dataclass(frozen=True)
class DoctorReport:
    hardware: HardwareInfo
    ollama_available: bool
    ollama_message: str
    ollama_version: str | None
    local_models: tuple[str, ...]
    recommended_profile: str
    decision_log: tuple[str, ...]
    app_data_path: str
    configured_profile: str
    configured_models: tuple[tuple[str, bool], ...]
    context_tokens: int | None
    warnings: tuple[str, ...] = ()

    def to_lines(self) -> list[str]:
        lines = [
            f"OS: {self.hardware.os_name} {self.hardware.os_version}",
            f"Python: {self.hardware.python_version}",
            f"CPU: {self.hardware.cpu}",
            f"RAM: {_fmt_optional_gb(self.hardware.ram_gb)}",
            (
                f"Ollama: {'available' if self.ollama_available else 'unavailable'} "
                f"- {self.ollama_message}"
            ),
            f"Ollama version: {self.ollama_version or 'unknown'}",
            f"Available models: {', '.join(self.local_models) if self.local_models else '(none)'}",
            f"Configured profile: {self.configured_profile}",
            f"Configured context tokens: {self.context_tokens or 'default'}",
            f"Recommended profile: {self.recommended_profile}",
            f"App data path: {self.app_data_path}",
            "Decision logic:",
        ]
        lines.extend(f"- {item}" for item in self.decision_log)
        if self.configured_models:
            lines.append("Configured models:")
            lines.extend(
                f"- {model}: {'present' if present else 'missing'}"
                for model, present in self.configured_models
            )
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {item}" for item in self.warnings)
        if self.hardware.gpus:
            lines.append("GPUs:")
            lines.extend(
                f"- {gpu.name} ({gpu.vram_mb or 'unknown'} MB VRAM via {gpu.source})"
                for gpu in self.hardware.gpus
            )
        else:
            lines.append("GPUs: none detected")
        return lines


def collect_hardware_info() -> HardwareInfo:
    return HardwareInfo(
        os_name=platform.system(),
        os_version=platform.version(),
        python_version=sys.version.split()[0],
        cpu=platform.processor() or platform.machine(),
        ram_gb=_detect_ram_gb(),
        gpus=tuple(_detect_gpus()),
    )


def recommend_profile(hardware: HardwareInfo) -> tuple[str, list[str]]:
    log: list[str] = []
    ram = hardware.ram_gb or 0
    max_vram = max((gpu.vram_mb or 0 for gpu in hardware.gpus), default=0)

    log.append(f"Detected RAM: {_fmt_optional_gb(hardware.ram_gb)}.")
    log.append(f"Detected max VRAM: {max_vram or 'unknown'} MB.")

    if ram and ram < 24:
        log.append("RAM below 24 GB: choose low_resource.")
        return "low_resource", log
    if max_vram and max_vram < 8192:
        log.append("VRAM below 8 GB: choose low_resource.")
        return "low_resource", log
    if ram >= 96 and max_vram >= 24576:
        log.append("Large RAM and VRAM detected: choose high_end.")
        log.append("qwen3-coder:480b still requires explicit user opt-in and is not default.")
        return "high_end", log
    log.append("Hardware appears suitable for recommended profile.")
    return "recommended", log


def build_doctor_report(config: DumboConfig, paths: AppPaths, ollama: OllamaClient) -> DoctorReport:
    hardware = collect_hardware_info()
    profile, decision_log = recommend_profile(hardware)
    available, message = ollama.is_available()
    version: str | None = None
    models: tuple[str, ...] = ()
    if available:
        version = ollama.version()
        try:
            models = tuple(ollama.tags())
        except Exception as exc:  # pragma: no cover - race with local service
            available = False
            message = str(exc)
    configured = _configured_models(config.app.profile)
    configured_status = tuple((model, model_is_available(models, model)) for model in configured)
    warnings = _doctor_warnings(config, hardware, version, models, configured)
    if not available:
        warnings.append("Start Ollama, then run: python -m dumbo doctor")
    return DoctorReport(
        hardware=hardware,
        ollama_available=available,
        ollama_message=message,
        ollama_version=version,
        local_models=models,
        recommended_profile=profile,
        decision_log=tuple(decision_log),
        app_data_path=str(paths.data_dir),
        configured_profile=config.app.profile,
        configured_models=configured_status,
        context_tokens=_effective_context_tokens(config, hardware),
        warnings=tuple(warnings),
    )


def _configured_models(profile_name: str) -> tuple[str, ...]:
    try:
        from dumbo.config import load_model_profile

        return load_model_profile(profile_name).ollama_models
    except Exception:
        return ()


def _effective_context_tokens(config: DumboConfig, hardware: HardwareInfo) -> int | None:
    if config.model.context_tokens is not None:
        return config.model.context_tokens
    if config.app.profile in {"recommended", "high_end"} and (
        hardware.ram_gb is None or hardware.ram_gb >= 48
    ):
        return 64000
    return None


def _doctor_warnings(
    config: DumboConfig,
    hardware: HardwareInfo,
    ollama_version: str | None,
    local_models: tuple[str, ...],
    configured_models: tuple[str, ...],
) -> list[str]:
    warnings: list[str] = []
    if any(model.startswith("qwen3-vl:") for model in configured_models) and (
        ollama_version is None or _version_less_than(ollama_version, "0.12.7")
    ):
        warnings.append("qwen3-vl requires Ollama 0.12.7 or newer.")
    if not hardware.gpus and "qwen3-coder:30b" in configured_models:
        warnings.append("CPU-only hardware is likely to run qwen3-coder:30b slowly.")
    missing = [model for model in configured_models if not model_is_available(local_models, model)]
    if missing:
        warnings.append(
            "Configured Ollama models are missing locally. Run: "
            f"python -m dumbo models pull --profile {config.app.profile}"
        )
    embedding_models = [model for model in configured_models if "embed" in model]
    for model in embedding_models:
        if not model_is_available(local_models, model):
            warnings.append(
                f"Configured embedding model {model} is missing; consider pulling it with Ollama."
            )
    return warnings


def model_is_available(local_models: tuple[str, ...] | list[str] | set[str], model: str) -> bool:
    local = set(local_models)
    if model in local:
        return True
    return ":" not in model and f"{model}:latest" in local


def _version_less_than(left: str, right: str) -> bool:
    def parts(value: str) -> tuple[int, ...]:
        parsed = []
        for item in value.split("."):
            digits = "".join(ch for ch in item if ch.isdigit())
            parsed.append(int(digits or 0))
        return tuple(parsed)

    return parts(left) < parts(right)


def _detect_ram_gb() -> float | None:
    if sys.platform == "win32":

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(  # type: ignore[attr-defined]
            ctypes.byref(status)
        ):
            return round(status.ullTotalPhys / (1024**3), 1)
        return None
    if sys.platform == "darwin":
        completed = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
        if completed.returncode == 0:
            return round(int(completed.stdout.strip()) / (1024**3), 1)
    meminfo = "/proc/meminfo"
    try:
        with open(meminfo, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / (1024**2), 1)
    except OSError:
        return None
    return None


def _detect_gpus() -> list[GpuInfo]:
    nvidia = _detect_nvidia_smi()
    if nvidia:
        return nvidia
    if sys.platform == "win32":
        return _detect_windows_gpus()
    return []


def _detect_nvidia_smi() -> list[GpuInfo]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    completed = subprocess.run(
        [
            exe,
            "--query-gpu=name,memory.total",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        return []
    gpus: list[GpuInfo] = []
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 2:
            try:
                vram = int(parts[1])
            except ValueError:
                vram = None
            gpus.append(GpuInfo(name=parts[0], vram_mb=vram, source="nvidia-smi"))
    return gpus


def _detect_windows_gpus() -> list[GpuInfo]:
    powershell = shutil.which("powershell")
    if not powershell:
        return []
    command = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        payload: Any = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    items = payload if isinstance(payload, list) else [payload]
    gpus: list[GpuInfo] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ram = item.get("AdapterRAM")
        vram = int(ram / (1024**2)) if isinstance(ram, int) and ram > 0 else None
        gpus.append(GpuInfo(name=str(item.get("Name", "Unknown GPU")), vram_mb=vram, source="CIM"))
    return gpus


def _fmt_optional_gb(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.1f} GB"
