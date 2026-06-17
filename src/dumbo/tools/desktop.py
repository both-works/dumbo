from __future__ import annotations

from typing import Any

from dumbo.paths import AppPaths
from dumbo.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult


class GetActiveWindowTool(BaseTool):
    name = "get_active_window"
    description = "Get the currently active native window title when desktop extras are installed."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            import pyautogui
        except ImportError:
            return ToolResult.failure("PyAutoGUI is not installed. Install Dumbo with .[desktop].")
        window = pyautogui.getActiveWindow()
        title = window.title if window else ""
        return ToolResult.success("Read active window.", {"title": title})


class ListWindowsTool(BaseTool):
    name = "list_windows"
    description = "List visible native windows using pywinauto."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            from pywinauto import Desktop
        except ImportError:
            return ToolResult.failure("pywinauto is not installed. Install Dumbo with .[desktop].")
        desktop = Desktop(backend="uia")
        windows = [
            {"title": win.window_text(), "process_id": win.process_id()}
            for win in desktop.windows()
        ]
        return ToolResult.success(f"Listed {len(windows)} windows.", {"windows": windows})


class ScreenshotTool(BaseTool):
    name = "screenshot"
    description = "Capture a screenshot and save it to Dumbo cache."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self, paths: AppPaths):
        self.paths = paths

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            import pyautogui
        except ImportError:
            return ToolResult.failure("PyAutoGUI is not installed. Install Dumbo with .[desktop].")
        pyautogui.FAILSAFE = True
        path = self.paths.cache_dir / "screenshots" / "latest.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image = pyautogui.screenshot()
        image.save(path)
        return ToolResult.success("Captured screenshot.", {"path": str(path)})


class ClickCoordinatesTool(BaseTool):
    name = "click_coordinates"
    description = "Click screen coordinates. Confirmation required unless explicitly trusted."
    risk_level = RiskLevel.WRITE_SAFE
    always_requires_confirmation = True
    allow_noninteractive_approval = False
    parameters_schema = {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "ui_token": {"type": ["string", "null"]},
        },
        "required": ["x", "y"],
    }

    def expected_impact(self, args: dict[str, Any]) -> str:
        return f"Clicks screen coordinates ({args.get('x')}, {args.get('y')})."

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.dry_run:
            return ToolResult.success(f"Would click coordinates ({args['x']}, {args['y']}).")
        try:
            import pyautogui
        except ImportError:
            return ToolResult.failure("PyAutoGUI is not installed. Install Dumbo with .[desktop].")
        pyautogui.FAILSAFE = True
        pyautogui.click(args["x"], args["y"])
        return ToolResult.success(f"Clicked ({args['x']}, {args['y']}).")


class TypeTextTool(BaseTool):
    name = "type_text"
    description = "Type text into the active app. Confirmation required by policy."
    risk_level = RiskLevel.WRITE_SAFE
    always_requires_confirmation = True
    allow_noninteractive_approval = False
    trusted_mode_can_allow = False
    parameters_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.dry_run:
            return ToolResult.success("Would type text into the active app.")
        try:
            import pyautogui
        except ImportError:
            return ToolResult.failure("PyAutoGUI is not installed. Install Dumbo with .[desktop].")
        pyautogui.FAILSAFE = True
        pyautogui.write(args["text"])
        return ToolResult.success("Typed text into active app.")


class HotkeyTool(BaseTool):
    name = "hotkey"
    description = "Press a keyboard shortcut in the active app."
    risk_level = RiskLevel.LOW_RISK_OPEN
    parameters_schema = {
        "type": "object",
        "properties": {"keys": {"type": "array"}},
        "required": ["keys"],
    }

    def classify_risk(self, args: dict[str, Any]) -> RiskLevel:
        keys = _normalize_hotkey(args.get("keys", []))
        if keys in {
            ("alt", "f4"),
            ("ctrl", "w"),
            ("ctrl", "s"),
            ("delete",),
            ("shift", "delete"),
        }:
            return RiskLevel.DESTRUCTIVE
        if keys in {("enter",), ("ctrl", "enter"), ("control", "enter")}:
            return RiskLevel.EXTERNAL_COMMITMENT
        if keys in {("win", "r"), ("windows", "r"), ("ctrl", "shift", "p")}:
            return RiskLevel.SHELL
        if keys in _SAFE_HOTKEYS:
            return RiskLevel.LOW_RISK_OPEN
        return RiskLevel.WRITE_SAFE

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        keys = [str(key) for key in args["keys"]]
        if context.dry_run:
            return ToolResult.success(f"Would press hotkey {'+'.join(keys)}.")
        try:
            import pyautogui
        except ImportError:
            return ToolResult.failure("PyAutoGUI is not installed. Install Dumbo with .[desktop].")
        pyautogui.FAILSAFE = True
        pyautogui.hotkey(*keys)
        return ToolResult.success(f"Pressed hotkey {'+'.join(keys)}.")


def desktop_tools(paths: AppPaths) -> list[BaseTool]:
    return [
        GetActiveWindowTool(),
        ListWindowsTool(),
        ScreenshotTool(paths),
        ClickCoordinatesTool(),
        TypeTextTool(),
        HotkeyTool(),
    ]


_SAFE_HOTKEYS = {
    ("esc",),
    ("escape",),
    ("tab",),
    ("shift", "tab"),
    ("left",),
    ("right",),
    ("up",),
    ("down",),
    ("pageup",),
    ("pagedown",),
    ("home",),
    ("end",),
    ("ctrl", "tab"),
    ("ctrl", "shift", "tab"),
    ("alt", "tab"),
}


def _normalize_hotkey(keys: Any) -> tuple[str, ...]:
    if not isinstance(keys, list):
        return ()
    normalized = []
    for key in keys:
        item = str(key).strip().casefold()
        if item == "control":
            item = "ctrl"
        if item == "cmd":
            item = "win"
        normalized.append(item)
    return tuple(normalized)
