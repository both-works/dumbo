from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from platformdirs import PlatformDirs
except ImportError:  # pragma: no cover - dependency is declared
    PlatformDirs = None  # type: ignore[assignment]


APP_AUTHOR = "Dumbo"
APP_NAME = "Dumbo"


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path
    cache_dir: Path
    log_dir: Path
    audit_db: Path
    memory_db: Path
    skills_dir: Path


def repository_root(start: Path | None = None) -> Path:
    candidates = []
    if start is not None:
        candidates.append(start.resolve())
    candidates.append(Path.cwd().resolve())
    candidates.append(Path(__file__).resolve())

    for candidate in candidates:
        current = candidate if candidate.is_dir() else candidate.parent
        for parent in [current, *current.parents]:
            if (parent / "pyproject.toml").exists() and (parent / "src" / "dumbo").exists():
                return parent
    return Path.cwd().resolve()


def app_paths() -> AppPaths:
    if PlatformDirs is not None:
        dirs = PlatformDirs(APP_NAME, APP_AUTHOR)
        data_dir = Path(dirs.user_data_dir)
        cache_dir = Path(dirs.user_cache_dir)
        log_dir = Path(dirs.user_log_dir)
    else:
        base = Path(os.environ.get("APPDATA", Path.home() / ".dumbo"))
        data_dir = base / APP_NAME
        cache_dir = data_dir / "cache"
        log_dir = data_dir / "logs"

    return AppPaths(
        data_dir=data_dir,
        cache_dir=cache_dir,
        log_dir=log_dir,
        audit_db=data_dir / "audit.sqlite3",
        memory_db=data_dir / "memory.sqlite3",
        skills_dir=data_dir / "skills",
    )


def ensure_app_dirs(paths: AppPaths | None = None) -> AppPaths:
    paths = paths or app_paths()
    for directory in [paths.data_dir, paths.cache_dir, paths.log_dir, paths.skills_dir]:
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def user_default_roots() -> list[Path]:
    home = Path.home()
    roots = [
        home,
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home / "Pictures",
        home / "Music",
        home / "Videos",
    ]
    return dedupe_existing_roots(roots)


def system_roots() -> list[Path]:
    if sys.platform == "win32":
        try:
            import ctypes

            drives_mask = ctypes.windll.kernel32.GetLogicalDrives()
        except (AttributeError, OSError):
            anchor = Path.home().anchor
            return dedupe_existing_roots([Path(anchor)] if anchor else [])

        roots = [
            Path(f"{chr(ord('A') + index)}:/") for index in range(26) if drives_mask & (1 << index)
        ]
        return dedupe_existing_roots(roots)
    return dedupe_existing_roots([Path("/")])


def dedupe_existing_roots(roots: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for root in roots:
        try:
            resolved = root.expanduser().resolve()
        except OSError:
            continue
        key = str(resolved).casefold() if sys.platform == "win32" else str(resolved)
        if key in seen:
            continue
        seen.add(key)
        result.append(resolved)
    return result


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
