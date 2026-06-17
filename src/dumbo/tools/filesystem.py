from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from dumbo.config import DumboConfig
from dumbo.paths import is_relative_to
from dumbo.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult, ToolValidationError

SENSITIVE_PATTERNS = [
    "*.kdbx",
    "*cookie*",
    "*cookies*",
    "*credential*",
    "*password*",
    "*secret*",
    "*token*",
    "*wallet*",
    ".env",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
]


class FilesystemPolicyMixin:
    def __init__(self, config: DumboConfig):
        self.config = config

    @property
    def allowed_roots(self) -> list[Path]:
        return [root.resolve() for root in self.config.allowed_roots]

    def resolve_allowed(self, value: str, *, must_exist: bool = False) -> Path:
        path = Path(value).expanduser()
        if must_exist and not path.exists():
            raise ToolValidationError(f"Path does not exist: {path}")
        try:
            resolved = path.resolve(strict=must_exist)
        except OSError as exc:
            raise ToolValidationError(f"Could not resolve path {path}: {exc}") from exc

        if not any(
            is_relative_to(resolved, root) or resolved == root for root in self.allowed_roots
        ):
            roots = ", ".join(str(root) for root in self.allowed_roots)
            raise ToolValidationError(
                f"Path is outside allowed roots: {resolved}. Allowed: {roots}"
            )
        return resolved

    def reject_sensitive(self, path: Path) -> None:
        if self.config.filesystem.allow_sensitive_reads:
            return
        parts = [path.name, *path.parts]
        lowered = [part.casefold() for part in parts]
        for pattern in SENSITIVE_PATTERNS:
            pattern_cf = pattern.casefold()
            if any(fnmatch.fnmatch(part, pattern_cf) for part in lowered):
                raise ToolValidationError(
                    f"Sensitive path blocked by default: {path}. "
                    "Set filesystem.allow_sensitive_reads=true only after explicit review."
                )
        sensitive_dirs = {".ssh", "credentials", "credential manager", "wallets"}
        if any(part in sensitive_dirs for part in lowered):
            raise ToolValidationError(f"Sensitive directory blocked by default: {path}")


class ListAllowedRootsTool(FilesystemPolicyMixin, BaseTool):
    name = "list_allowed_roots"
    description = "List configured filesystem roots Dumbo is allowed to inspect."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.success(
            "Allowed roots listed.",
            {"roots": [str(root) for root in self.allowed_roots]},
        )


class ListDirTool(FilesystemPolicyMixin, BaseTool):
    name = "list_dir"
    description = "List files and folders inside an allowed directory."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        path = self.resolve_allowed(args["path"], must_exist=True)
        if not path.is_dir():
            return ToolResult.failure(f"Not a directory: {path}")
        entries = []
        for child in sorted(path.iterdir(), key=lambda item: item.name.casefold()):
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "type": "directory" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )
        return ToolResult.success(f"Listed {len(entries)} entries in {path}.", {"entries": entries})


class SearchFilesTool(FilesystemPolicyMixin, BaseTool):
    name = "search_files"
    description = "Search allowed roots by filename query and optional extensions."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "roots": {"type": "array"},
            "extensions": {"type": "array"},
            "max_results": {"type": "integer"},
        },
        "required": ["query"],
    }

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        query = str(args["query"]).casefold()
        max_results = int(args.get("max_results", 50))
        roots_arg = args.get("roots") or [str(root) for root in self.allowed_roots]
        roots = [self.resolve_allowed(str(root), must_exist=True) for root in roots_arg]
        extensions = {
            str(ext).casefold().lstrip(".")
            for ext in args.get("extensions", [])
            if str(ext).strip()
        }
        results: list[dict[str, Any]] = []

        for root in roots:
            if not root.is_dir():
                continue
            for current, dirs, files in os.walk(root):
                dirs[:] = [name for name in dirs if not _is_hidden_or_sensitive(name)]
                for filename in files:
                    if query not in filename.casefold():
                        continue
                    path = Path(current) / filename
                    if extensions and path.suffix.casefold().lstrip(".") not in extensions:
                        continue
                    try:
                        self.reject_sensitive(path)
                    except ToolValidationError:
                        continue
                    results.append(
                        {"path": str(path), "name": filename, "size": path.stat().st_size}
                    )
                    if len(results) >= max_results:
                        return ToolResult.success(
                            f"Found {len(results)} matching files.",
                            {"results": results},
                        )
        return ToolResult.success(f"Found {len(results)} matching files.", {"results": results})


class ReadTextFileTool(FilesystemPolicyMixin, BaseTool):
    name = "read_text_file"
    description = "Read a text file inside an allowed root, capped by max_chars."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "max_chars": {"type": "integer"},
        },
        "required": ["path"],
    }

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        path = self.resolve_allowed(args["path"], must_exist=True)
        self.reject_sensitive(path)
        if not path.is_file():
            return ToolResult.failure(f"Not a file: {path}")
        max_chars = int(args.get("max_chars", 8000))
        try:
            content = path.read_text(encoding="utf-8")[:max_chars]
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="replace")[:max_chars]
        return ToolResult.success(
            f"Read {len(content)} characters from {path}.", {"content": content}
        )


class OpenPathTool(FilesystemPolicyMixin, BaseTool):
    name = "open_path"
    description = "Open an allowed file or folder with the operating system default handler."
    risk_level = RiskLevel.LOW_RISK_OPEN
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        path = self.resolve_allowed(args["path"], must_exist=True)
        if context.dry_run:
            return ToolResult.success(f"Would open {path}.")
        _open_path(path)
        return ToolResult.success(f"Opened {path}.", {"path": str(path)})


class CreateFolderTool(FilesystemPolicyMixin, BaseTool):
    name = "create_folder"
    description = "Create a folder inside an allowed root."
    risk_level = RiskLevel.WRITE_SAFE
    dry_run_supported = True
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        path = self.resolve_allowed(args["path"], must_exist=False)
        if context.dry_run:
            return ToolResult.success(f"Would create folder {path}.")
        path.mkdir(parents=True, exist_ok=True)
        return ToolResult.success(f"Created folder {path}.", {"path": str(path)})


class WriteTextFileTool(FilesystemPolicyMixin, BaseTool):
    name = "write_text_file"
    description = "Create, append, or overwrite a text file inside an allowed root."
    risk_level = RiskLevel.WRITE_SAFE
    dry_run_supported = True
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "mode": {"type": "string"},
        },
        "required": ["path", "content", "mode"],
    }

    def classify_risk(self, args: dict[str, Any]) -> RiskLevel:
        return RiskLevel.DESTRUCTIVE if args.get("mode") == "overwrite" else RiskLevel.WRITE_SAFE

    def validate_args(self, args: dict[str, Any]) -> None:
        super().validate_args(args)
        if args["mode"] not in {"create", "append", "overwrite"}:
            raise ToolValidationError("mode must be create, append, or overwrite")

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        path = self.resolve_allowed(args["path"], must_exist=False)
        self.reject_sensitive(path)
        mode = args["mode"]
        if mode == "create" and path.exists():
            return ToolResult.failure(f"File already exists: {path}")
        if context.dry_run:
            return ToolResult.success(f"Would {mode} text file {path}.")
        if mode == "append":
            with path.open("a", encoding="utf-8") as handle:
                handle.write(args["content"])
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
        return ToolResult.success(f"Wrote text file {path}.", {"path": str(path), "mode": mode})


class MoveFileTool(FilesystemPolicyMixin, BaseTool):
    name = "move_file"
    description = "Move or rename a file between allowed paths."
    risk_level = RiskLevel.WRITE_SAFE
    dry_run_supported = True
    parameters_schema = {
        "type": "object",
        "properties": {"src": {"type": "string"}, "dst": {"type": "string"}},
        "required": ["src", "dst"],
    }

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        src = self.resolve_allowed(args["src"], must_exist=True)
        dst = self.resolve_allowed(args["dst"], must_exist=False)
        self.reject_sensitive(src)
        self.reject_sensitive(dst)
        if context.dry_run:
            return ToolResult.success(f"Would move {src} to {dst}.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return ToolResult.success(f"Moved {src} to {dst}.", {"src": str(src), "dst": str(dst)})


class DeleteFileTool(FilesystemPolicyMixin, BaseTool):
    name = "delete_file"
    description = "Delete a file inside an allowed root. Always confirmation gated."
    risk_level = RiskLevel.DESTRUCTIVE
    dry_run_supported = True
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        path = self.resolve_allowed(args["path"], must_exist=True)
        self.reject_sensitive(path)
        if not path.is_file():
            return ToolResult.failure(f"Refusing to delete non-file path: {path}")
        if context.dry_run:
            return ToolResult.success(f"Would delete file {path}.")
        path.unlink()
        return ToolResult.success(f"Deleted file {path}.", {"path": str(path)})


def filesystem_tools(config: DumboConfig) -> list[BaseTool]:
    return [
        ListAllowedRootsTool(config),
        ListDirTool(config),
        SearchFilesTool(config),
        ReadTextFileTool(config),
        OpenPathTool(config),
        CreateFolderTool(config),
        WriteTextFileTool(config),
        MoveFileTool(config),
        DeleteFileTool(config),
    ]


def _open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _is_hidden_or_sensitive(name: str) -> bool:
    lowered = name.casefold()
    return lowered.startswith(".") or any(
        fnmatch.fnmatch(lowered, pattern) for pattern in SENSITIVE_PATTERNS
    )
