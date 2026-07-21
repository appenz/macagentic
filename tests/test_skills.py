from pathlib import Path

import pytest

from macagentic.agent.skills import load_available_skills, load_skills


def _write_skill(
    root: Path,
    name: str,
    frontmatter: str,
    body: str,
) -> None:
    directory = root / name
    directory.mkdir()
    (directory / "SKILL.md").write_text(
        f"---\n{frontmatter.strip()}\n---\n\n{body}\n"
    )


def test_loads_skills_by_folder_name_and_renders_model_list(
    tmp_path: Path,
) -> None:
    _write_skill(
        tmp_path,
        "alpha-skill",
        """
name: ignored-name
description: Do alpha work.
""",
        "Alpha instructions.",
    )
    _write_skill(
        tmp_path,
        "hidden-skill",
        """
description: User-only work.
disable-model-invocation: true
user-invocable: true
""",
        "Hidden instructions.",
    )
    _write_skill(
        tmp_path,
        "model-skill",
        """
description: Model-only work.
user-invocable: false
""",
        "Model instructions.",
    )

    catalog = load_skills(tmp_path)

    assert [skill.name for skill in catalog.skills] == [
        "alpha-skill",
        "hidden-skill",
        "model-skill",
    ]
    assert catalog.render_prompt() == (
        "alpha-skill - Do alpha work. - "
        "skills/alpha-skill/SKILL.md\n"
        "model-skill - Model-only work. - "
        "skills/model-skill/SKILL.md"
    )


def test_expands_only_whitespace_delimited_user_invocable_skills(
    tmp_path: Path,
) -> None:
    _write_skill(
        tmp_path,
        "alpha-skill",
        "description: Do alpha work.",
        "Alpha instructions.",
    )
    _write_skill(
        tmp_path,
        "hidden-skill",
        """
description: User-only work.
disable-model-invocation: true
""",
        "Hidden instructions.",
    )
    _write_skill(
        tmp_path,
        "model-skill",
        """
description: Model-only work.
user-invocable: false
""",
        "Model instructions.",
    )
    catalog = load_skills(tmp_path)

    expanded = catalog.expand_commands(
        "/alpha-skill details\n"
        "/hidden-skill\n"
        "/model-skill /unknown x/alpha-skill /alpha-skill,"
    )

    assert expanded == (
        "Alpha instructions. details\n"
        "Hidden instructions.\n"
        "/model-skill /unknown x/alpha-skill /alpha-skill,"
    )
    assert "description:" not in expanded


def test_missing_skills_directory_returns_empty_catalog(
    tmp_path: Path,
) -> None:
    catalog = load_skills(tmp_path / "missing")

    assert catalog.skills == ()
    assert catalog.expand_commands("/exit") == "/exit"
    assert catalog.render_prompt() == ""


def test_loads_user_and_tool_skills(tmp_path: Path) -> None:
    tools_root = tmp_path / "tools"
    user_root = tmp_path / "user-skills"
    tool_skills = tools_root / "calendar" / "skills"
    tool_skills.mkdir(parents=True)
    user_root.mkdir()
    _write_skill(
        tool_skills,
        "calendar-agenda",
        "description: Read the calendar.",
        "Calendar instructions.",
    )
    _write_skill(
        user_root,
        "personal-notes",
        "description: Read personal notes.",
        "Notes instructions.",
    )

    catalog = load_available_skills(user_root, tools_root)

    assert [skill.name for skill in catalog.skills] == [
        "calendar-agenda",
        "personal-notes",
    ]
    assert catalog.skills[0].source == (
        tool_skills / "calendar-agenda" / "SKILL.md"
    ).resolve()
    assert (
        "skills/calendar-agenda/SKILL.md"
        in catalog.render_prompt()
    )


def test_rejects_duplicate_user_and_tool_skill_names(tmp_path: Path) -> None:
    tools_root = tmp_path / "tools"
    user_root = tmp_path / "user-skills"
    tool_skills = tools_root / "calendar" / "skills"
    tool_skills.mkdir(parents=True)
    user_root.mkdir()
    for root in (tool_skills, user_root):
        _write_skill(
            root,
            "duplicate",
            "description: Duplicate skill.",
            "Instructions.",
        )

    with pytest.raises(ValueError, match="Duplicate skill 'duplicate'"):
        load_available_skills(user_root, tools_root)


def test_rejects_non_boolean_invocation_flags(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "invalid",
        """
description: Invalid metadata.
user-invocable: "true"
""",
        "Instructions.",
    )

    with pytest.raises(ValueError, match="user-invocable must be a boolean"):
        load_skills(tmp_path)
