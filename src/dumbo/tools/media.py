from __future__ import annotations

import ctypes
import sys
from typing import Any

from dumbo.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult, ToolValidationError

VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
KEYEVENTF_KEYUP = 0x0002


class MediaKeyTool(BaseTool):
    risk_level = RiskLevel.LOW_RISK_OPEN
    parameters_schema = {"type": "object", "properties": {}, "required": []}
    virtual_key: int = 0
    action_name: str = ""

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.dry_run:
            return ToolResult.success(f"Would send media key {self.action_name}.")
        _press_key(self.virtual_key)
        return ToolResult.success(f"Sent media key {self.action_name}.")


class MediaPlayPauseTool(MediaKeyTool):
    name = "media_play_pause"
    description = "Toggle media play/pause."
    virtual_key = VK_MEDIA_PLAY_PAUSE
    action_name = "play/pause"


class MediaNextTool(MediaKeyTool):
    name = "media_next"
    description = "Skip to next media track."
    virtual_key = VK_MEDIA_NEXT_TRACK
    action_name = "next"


class MediaPreviousTool(MediaKeyTool):
    name = "media_previous"
    description = "Skip to previous media track."
    virtual_key = VK_MEDIA_PREV_TRACK
    action_name = "previous"


class MuteToggleTool(MediaKeyTool):
    name = "mute_toggle"
    description = "Toggle system mute."
    virtual_key = VK_VOLUME_MUTE
    action_name = "mute"


class SetVolumeTool(BaseTool):
    name = "set_volume"
    description = "Set volume approximately by stepping media keys. Best-effort fallback."
    risk_level = RiskLevel.LOW_RISK_OPEN
    parameters_schema = {
        "type": "object",
        "properties": {"level": {"type": "integer"}},
        "required": ["level"],
    }

    def validate_args(self, args: dict[str, Any]) -> None:
        super().validate_args(args)
        if not 0 <= int(args["level"]) <= 100:
            raise ToolValidationError("level must be between 0 and 100")

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        level = int(args["level"])
        if context.dry_run:
            return ToolResult.success(f"Would set volume to approximately {level}.")
        for _ in range(50):
            _press_key(VK_VOLUME_DOWN)
        for _ in range(round(level / 2)):
            _press_key(VK_VOLUME_UP)
        return ToolResult.success(f"Set volume to approximately {level}.")


def media_tools() -> list[BaseTool]:
    return [
        MediaPlayPauseTool(),
        MediaNextTool(),
        MediaPreviousTool(),
        SetVolumeTool(),
        MuteToggleTool(),
    ]


def _press_key(vk: int) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Media key fallback is implemented only for Windows.")
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)  # type: ignore[attr-defined]
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)  # type: ignore[attr-defined]
