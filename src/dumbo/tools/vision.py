from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from dumbo.agent.ollama_client import OllamaClient, OllamaError
from dumbo.config import DumboConfig, ModelProfile
from dumbo.paths import AppPaths, is_relative_to
from dumbo.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult, ToolValidationError
from dumbo.tools.filesystem import FilesystemPolicyMixin

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class VisionImagePolicyMixin(FilesystemPolicyMixin):
    def __init__(self, config: DumboConfig, paths: AppPaths):
        super().__init__(config)
        self.paths = paths

    @property
    def image_roots(self) -> list[Path]:
        return [*self.allowed_roots, self.paths.cache_dir.resolve()]

    def resolve_image(self, value: str) -> Path:
        path = Path(value).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ToolValidationError(f"Could not resolve image path {path}: {exc}") from exc
        if resolved.suffix.casefold() not in IMAGE_EXTENSIONS:
            raise ToolValidationError("Vision tools accept only common image file extensions.")
        if not any(is_relative_to(resolved, root) or resolved == root for root in self.image_roots):
            roots = ", ".join(str(root) for root in self.image_roots)
            raise ToolValidationError(
                f"Image path is outside allowed roots: {resolved}. Allowed: {roots}"
            )
        self.reject_sensitive(resolved)
        size = resolved.stat().st_size
        if size > MAX_IMAGE_BYTES:
            raise ToolValidationError(
                f"Image file is too large: {size} bytes. Limit: {MAX_IMAGE_BYTES} bytes."
            )
        return resolved


class ScreenshotDescribeTool(VisionImagePolicyMixin, BaseTool):
    name = "screenshot_describe"
    description = "Ask the configured local vision model to describe a screenshot."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {
        "type": "object",
        "properties": {
            "image_path": {"type": "string"},
            "question": {"type": "string"},
        },
        "required": ["image_path", "question"],
    }

    def __init__(
        self, ollama: OllamaClient, profile: ModelProfile, config: DumboConfig, paths: AppPaths
    ):
        super().__init__(config, paths)
        self.ollama = ollama
        self.profile = profile

    def validate_args(self, args: dict[str, Any]) -> None:
        super().validate_args(args)
        self.resolve_image(args["image_path"])

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        image = _read_image_base64(self.resolve_image(args["image_path"]))
        try:
            response = self.ollama.chat(
                model=self.profile.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": args["question"],
                        "images": [image],
                    }
                ],
                stream=False,
            )
        except OllamaError as exc:
            return ToolResult.failure(f"Vision model unavailable: {exc}")
        content = response.get("message", {}).get("content", "")
        return ToolResult.success("Vision model answered.", {"answer": content})


class LocateUiElementTool(VisionImagePolicyMixin, BaseTool):
    name = "locate_ui_element_from_screenshot"
    description = "Ask the vision model to propose coordinates for a UI element from a screenshot."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {
        "type": "object",
        "properties": {
            "image_path": {"type": "string"},
            "description": {"type": "string"},
        },
        "required": ["image_path", "description"],
    }

    def __init__(
        self, ollama: OllamaClient, profile: ModelProfile, config: DumboConfig, paths: AppPaths
    ):
        super().__init__(config, paths)
        self.ollama = ollama
        self.profile = profile

    def validate_args(self, args: dict[str, Any]) -> None:
        super().validate_args(args)
        self.resolve_image(args["image_path"])

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        question = (
            "Locate this UI element and answer only JSON with x, y, confidence, and rationale: "
            + args["description"]
        )
        image = _read_image_base64(self.resolve_image(args["image_path"]))
        try:
            response = self.ollama.chat(
                model=self.profile.vision_model,
                messages=[{"role": "user", "content": question, "images": [image]}],
                stream=False,
                format_value="json",
            )
        except OllamaError as exc:
            return ToolResult.failure(f"Vision model unavailable: {exc}")
        content = response.get("message", {}).get("content", "")
        return ToolResult.success("Vision model proposed a location.", {"proposal": content})


def vision_tools(
    ollama: OllamaClient, profile: ModelProfile, config: DumboConfig, paths: AppPaths
) -> list[BaseTool]:
    return [
        ScreenshotDescribeTool(ollama, profile, config, paths),
        LocateUiElementTool(ollama, profile, config, paths),
    ]


def _read_image_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")
