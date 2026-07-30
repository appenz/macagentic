from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SESSION_VERSION = 1


@dataclass(frozen=True)
class SavedTab:
    id: int
    title: str
    input_text: str
    messages: list[dict]
    events: list[dict[str, Any]]


@dataclass(frozen=True)
class SavedSession:
    workspace: str
    active_index: int
    tabs: list[SavedTab]


def session_path() -> Path:
    return Path.home() / ".tmpagent" / "open-tabs.json"


def load_session(
    workspace: Path,
    *,
    path: Path | None = None,
) -> SavedSession | None:
    source = path or session_path()
    if not source.exists():
        return None
    data = json.loads(source.read_text())
    if data["version"] != SESSION_VERSION:
        raise ValueError(f"Unsupported session version: {data['version']}")
    expected = str(workspace.resolve())
    if data["workspace"] != expected:
        raise RuntimeError(
            f"Saved workspace is {data['workspace']}, current workspace is {expected}"
        )
    return SavedSession(
        workspace=data["workspace"],
        active_index=data["active_index"],
        tabs=[SavedTab(**tab) for tab in data["tabs"]],
    )


def save_session(
    session: SavedSession,
    *,
    path: Path | None = None,
) -> None:
    destination = path or session_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"version": SESSION_VERSION, **asdict(session)},
            separators=(",", ":"),
        )
    )
    temporary.replace(destination)
