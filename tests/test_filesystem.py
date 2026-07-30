from pathlib import Path

import pytest

from macagentic.agent.filesystem import (
    create_agent_root,
    render_filesystem_instructions,
)
from macagentic.agent.skills import Skill, SkillCatalog


def test_reuses_existing_agent_root_unchanged(tmp_path: Path) -> None:
    roots = tmp_path / "roots"
    stale_root = roots / "7"
    stale_root.mkdir(parents=True)
    (stale_root / "stale.txt").write_text("old")

    root = create_agent_root(7, SkillCatalog(), {}, roots_directory=roots)

    assert root == stale_root
    assert (root / "stale.txt").read_text() == "old"


def test_creates_agent_root_with_short_mounts(tmp_path: Path) -> None:
    roots = tmp_path / "roots"
    skill_directory = tmp_path / "source" / "demo"
    skill_directory.mkdir(parents=True)
    skill_file = skill_directory / "SKILL.md"
    skill_file.write_text("instructions")
    catalog = SkillCatalog(
        (
            Skill(
                name="demo",
                description="Demo skill.",
                body="instructions",
                source=skill_file,
            ),
        )
    )
    notes = tmp_path / "notes"
    notes.mkdir()

    root = create_agent_root(
        8,
        catalog,
        {"documents/notes": str(notes)},
        roots_directory=roots,
    )

    assert root == roots / "8"
    assert (root / "skills" / "demo").readlink() == skill_directory
    assert (root / "documents").is_dir()
    assert (root / "documents" / "notes").readlink() == notes


def test_rejects_reserved_or_missing_mounts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid mount name"):
        create_agent_root(
            1,
            SkillCatalog(),
            {"skills": str(tmp_path)},
            roots_directory=tmp_path / "roots",
        )

    with pytest.raises(ValueError, match="not a directory"):
        create_agent_root(
            2,
            SkillCatalog(),
            {"notes": str(tmp_path / "missing")},
            roots_directory=tmp_path / "roots",
        )

    with pytest.raises(ValueError, match="overlap"):
        create_agent_root(
            3,
            SkillCatalog(),
            {
                "notes": str(tmp_path),
                "notes/private": str(tmp_path),
            },
            roots_directory=tmp_path / "roots",
        )


def test_filesystem_prompt_lists_only_configured_mounts() -> None:
    prompt = render_filesystem_instructions(
        {
            "notes/private": "~/notes/private",
            "notes/a16z": "~/notes/a16z",
        }
    )

    assert "`skills/` - available agent skills" in prompt
    assert "`notes/private/` - configured user directory" in prompt
    assert "`notes/a16z/` - configured user directory" in prompt
    assert "tools/" not in prompt
    assert "storage/" not in prompt
