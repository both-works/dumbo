from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from dumbo.config import DumboConfig
from dumbo.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult, ToolValidationError

DEFAULT_APP_ALIASES = {
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "explorer": "explorer",
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "firefox": "firefox",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "cmd": "cmd",
    "powershell": "powershell",
    "pwsh": "pwsh",
}
SHELL_ALIASES = {"cmd", "powershell", "pwsh"}


class OpenAppTool(BaseTool):
    name = "open_app"
    description = "Open an application by known name or explicit executable path."
    risk_level = RiskLevel.LOW_RISK_OPEN
    allow_noninteractive_approval = False
    trusted_mode_can_allow = False
    parameters_schema = {
        "type": "object",
        "properties": {"name_or_path": {"type": "string"}},
        "required": ["name_or_path"],
    }

    def __init__(self, config: DumboConfig):
        self.config = config

    def classify_risk(self, args: dict[str, Any]) -> RiskLevel:
        target = str(args.get("name_or_path", "")).strip()
        alias = target.casefold()
        if alias in SHELL_ALIASES:
            return RiskLevel.SHELL
        if _looks_like_path(target):
            path = Path(target).expanduser()
            if _path_is_allowlisted(path, self.config.app.allowed_executable_paths):
                return RiskLevel.LOW_RISK_OPEN
            return RiskLevel.WRITE_SAFE
        aliases = {**DEFAULT_APP_ALIASES, **self.config.app.app_aliases}
        if alias in aliases:
            return RiskLevel.LOW_RISK_OPEN
        return RiskLevel.WRITE_SAFE

    def validate_args(self, args: dict[str, Any]) -> None:
        super().validate_args(args)
        target = args["name_or_path"].strip()
        if not target:
            raise ToolValidationError("Application name cannot be empty")
        aliases = {**DEFAULT_APP_ALIASES, **self.config.app.app_aliases}
        if _looks_like_path(target):
            path = Path(target).expanduser()
            if path.suffix.casefold() != ".exe":
                raise ToolValidationError("Explicit app paths must point to .exe files.")
            return
        if target.casefold() not in aliases and not _is_simple_app_name(target):
            raise ToolValidationError(
                f"Unknown app alias: {target}. Use a simple app name or configure app.app_aliases."
            )

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        target = args["name_or_path"].strip()
        if context.dry_run:
            return ToolResult.success(f"Would open app {target}.")
        if _looks_like_path(target):
            path = Path(target).expanduser()
            if not path.exists():
                return ToolResult.failure(f"Application path does not exist: {path}")
            if sys.platform == "win32":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen([str(path)])
        else:
            aliases = {**DEFAULT_APP_ALIASES, **self.config.app.app_aliases}
            target = aliases.get(target.casefold(), target)
            try:
                _open_app_target(target)
            except OSError as exc:
                return ToolResult.failure(f"Could not open app {target}: {exc}")
        return ToolResult.success(f"Opened app {target}.", {"target": target})

    def expected_impact(self, args: dict[str, Any]) -> str:
        target = str(args.get("name_or_path", "")).strip()
        return f"Starts the application or executable: {target}"


class ListRunningAppsTool(BaseTool):
    name = "list_running_apps"
    description = "List running processes visible to the current user."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if sys.platform == "win32":
            command = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-Process | Select-Object ProcessName,Id,MainWindowTitle | ConvertTo-Json",
            ]
        else:
            command = ["ps", "-eo", "pid,comm"]
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
        if completed.returncode != 0:
            return ToolResult.failure("Could not list running apps.", completed.stderr)
        return ToolResult.success("Listed running apps.", {"raw": completed.stdout[-16000:]})


class FocusAppTool(BaseTool):
    name = "focus_app"
    description = "Focus a native window by title or process name using pywinauto when available."
    risk_level = RiskLevel.LOW_RISK_OPEN
    parameters_schema = {
        "type": "object",
        "properties": {"window_title_or_process": {"type": "string"}},
        "required": ["window_title_or_process"],
    }

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            from pywinauto import Desktop
        except ImportError:
            return ToolResult.failure("pywinauto is not installed. Install Dumbo with .[desktop].")
        query = args["window_title_or_process"].casefold()
        desktop = Desktop(backend="uia")
        for window in desktop.windows():
            title = window.window_text()
            process = str(window.process_id())
            if query in title.casefold() or query == process:
                if context.dry_run:
                    return ToolResult.success(f"Would focus window {title}.")
                window.set_focus()
                return ToolResult.success(f"Focused window {title}.")
        return ToolResult.failure(
            f"No matching window found for {args['window_title_or_process']}."
        )


class CloseAppTool(BaseTool):
    name = "close_app"
    description = "Close an app by process ID or window title. Confirmation required."
    risk_level = RiskLevel.DESTRUCTIVE
    parameters_schema = {
        "type": "object",
        "properties": {"process_or_window": {"type": "string"}},
        "required": ["process_or_window"],
    }

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        target = args["process_or_window"].strip()
        if context.dry_run:
            return ToolResult.success(f"Would close app/window {target}.")
        if sys.platform == "win32" and target.isdigit():
            completed = subprocess.run(
                ["taskkill", "/PID", target],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if completed.returncode != 0:
                return ToolResult.failure("Could not close process.", completed.stderr)
            return ToolResult.success(f"Closed process {target}.")
        return ToolResult.failure("Close by window title requires .[desktop] and is not automatic.")


def apps_tools(config: DumboConfig) -> list[BaseTool]:
    return [OpenAppTool(config), ListRunningAppsTool(), FocusAppTool(), CloseAppTool()]


def _looks_like_path(value: str) -> bool:
    return "\\" in value or "/" in value or value.endswith(".exe") or Path(value).is_absolute()


def _is_simple_app_name(value: str) -> bool:
    return bool(value) and not any(char in value for char in "\r\n;&|<>")


def _open_app_target(target: str) -> None:
    executable = shutil.which(target)
    if executable is not None:
        subprocess.Popen([executable], shell=False)
        return
    if sys.platform == "win32":
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Start-Process -FilePath $args[0]",
                target,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if completed.returncode == 0:
            return
    subprocess.Popen([target], shell=False)


def _path_is_allowlisted(path: Path, allowlist: tuple[Path, ...]) -> bool:
    try:
        resolved = path.expanduser().resolve(strict=False)
    except OSError:
        return False
    for item in allowlist:
        allowed = item.expanduser().resolve(strict=False)
        if resolved == allowed:
            return True
        if allowed.is_dir() and str(resolved).casefold().startswith(str(allowed).casefold()):
            return True
    return False
