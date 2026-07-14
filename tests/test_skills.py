from pathlib import Path

import pytest

from macagentic.agent.skills import load_skills


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
        "# Skills\n"
        "You have access to agent skills that help you fulfill tasks.\n"
        "Load skills by reading the file "
        "~/.agents/skills/<skillname>/SKILL.md\n"
        "Below a list of skills, the format is "
        "<skill name> - Description.\n\n"
        "alpha-skill - Do alpha work.\n"
        "model-skill - Model-only work."
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
    assert catalog.render_prompt().endswith(
        "Below a list of skills, the format is <skill name> - Description."
    )


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
