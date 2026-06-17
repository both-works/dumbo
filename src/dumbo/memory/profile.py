from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserProfile:
    preferred_name: str | None = None
    common_project_roots: tuple[str, ...] = ()
    common_apps: tuple[str, ...] = ()
