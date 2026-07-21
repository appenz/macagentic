from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as config_file:
        return tomllib.load(config_file)


def _deep_merge(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True)
class MacAgenticConfig:
    model: str = "openai/gpt-5-mini"
    openai_api_key: str = ""
    brave_api_key: str = ""
    custom_prompt: str = ""
    mounts: dict[str, str] = field(default_factory=dict)


def _from_dict(data: dict[str, Any]) -> MacAgenticConfig:
    mounts = data.get("mounts", {})
    if not isinstance(mounts, dict) or not all(
        isinstance(name, str) and isinstance(path, str)
        for name, path in mounts.items()
    ):
        raise ValueError("Config 'mounts' must map names to directory paths.")
    return MacAgenticConfig(
        model=str(data.get("model", "openai/gpt-5-mini") or ""),
        openai_api_key=str(data.get("openai_api_key", "") or ""),
        brave_api_key=str(data.get("brave_api_key", "") or ""),
        custom_prompt=str(data.get("custom_prompt", "") or ""),
        mounts=dict(mounts),
    )


def load_config(project_root: Path | None = None) -> MacAgenticConfig:
    root = project_root or _project_root()
    project_config = _load_toml(root / "config" / "config.toml")
    user_config = _load_toml(
        Path("~/.config/macagentic/config.toml").expanduser()
    )
    return _from_dict(_deep_merge(project_config, user_config))
