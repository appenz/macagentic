from __future__ import annotations

import re
import shutil
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from macagentic.agent.skills import SkillCatalog


RESERVED_ROOT_NAMES = frozenset({"skills"})
MOUNT_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def create_agent_root(
    agent_id: int,
    skill_catalog: SkillCatalog,
    user_mounts: Mapping[str, str],
    *,
    roots_directory: Path | None = None,
) -> Path:
    if agent_id < 1:
        raise ValueError("Agent ID must be a positive integer.")

    parent = (
        roots_directory or Path.home() / ".tmpagent"
    ).expanduser()
    root = parent / str(agent_id)
    if root.is_symlink():
        root.unlink()
    elif root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    skills_directory = root / "skills"
    skills_directory.mkdir()
    for skill in skill_catalog.skills:
        if skill.source is not None:
            (skills_directory / skill.name).symlink_to(
                skill.source.parent,
                target_is_directory=True,
            )

    mount_paths = {
        name: _validate_mount_name(name)
        for name in user_mounts
    }
    _validate_mount_overlaps(mount_paths)
    for name, configured_path in user_mounts.items():
        target = Path(configured_path).expanduser()
        if not target.is_dir():
            raise ValueError(
                f"Mount '{name}' target is not a directory: {target}"
            )
        mount_path = root.joinpath(*mount_paths[name].parts)
        mount_path.parent.mkdir(parents=True, exist_ok=True)
        mount_path.symlink_to(
            target.resolve(),
            target_is_directory=True,
        )

    return root


def render_filesystem_instructions(user_mounts: Mapping[str, str]) -> str:
    lines = [
        "# Agent Filesystem",
        "",
        "Your current working directory is this agent's temporary root.",
        "Use short paths relative to it. `~` remains the user's normal home",
        "directory, while `$AGENT_ROOT` contains the absolute path to this root.",
        "Directories in the agent root may be symlinks; use `rg --follow` or `find -L`.",
        "",
        "Available directories:",
        "- `skills/` - available agent skills",
    ]
    lines.extend(
        f"- `{name}/` - configured user directory"
        for name in user_mounts
    )
    return "\n".join(lines)


def _validate_mount_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or not path.parts
        or path.parts[0] in RESERVED_ROOT_NAMES
        or any(
            part in {".", ".."}
            or not MOUNT_COMPONENT_PATTERN.fullmatch(part)
            for part in path.parts
        )
    ):
        raise ValueError(
            f"Invalid mount name '{name}'; use a safe relative path "
            "outside reserved roots: skills"
        )
    return path


def _validate_mount_overlaps(
    mount_paths: Mapping[str, PurePosixPath],
) -> None:
    names = list(mount_paths)
    for index, name in enumerate(names):
        path = mount_paths[name]
        for other_name in names[index + 1 :]:
            other = mount_paths[other_name]
            if (
                path == other
                or path in other.parents
                or other in path.parents
            ):
                raise ValueError(
                    f"Mount paths overlap: '{name}' and '{other_name}'"
                )
