import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    disable_model_invocation: bool = False
    user_invocable: bool = True


@dataclass(frozen=True)
class SkillCatalog:
    skills: tuple[Skill, ...] = ()

    def render_prompt(self) -> str:
        lines = [
            "# Skills",
            "You have access to agent skills that help you fulfill tasks.",
            (
                "Load skills by reading the file "
                "~/.agents/skills/<skillname>/SKILL.md"
            ),
            (
                "Below a list of skills, the format is "
                "<skill name> - Description."
            ),
            "",
        ]
        lines.extend(
            f"{skill.name} - {skill.description}"
            for skill in self.skills
            if not skill.disable_model_invocation
        )
        return "\n".join(lines).rstrip()

    def expand_commands(self, text: str) -> str:
        invocable = {
            skill.name: skill.body
            for skill in self.skills
            if skill.user_invocable
        }
        if not invocable:
            return text

        names = "|".join(
            re.escape(name)
            for name in sorted(invocable, key=len, reverse=True)
        )
        pattern = re.compile(rf"(?<!\S)/(?P<name>{names})(?!\S)")
        return pattern.sub(
            lambda match: invocable[match.group("name")],
            text,
        )


EMPTY_SKILL_CATALOG = SkillCatalog()


def load_skills(directory: Path | None = None) -> SkillCatalog:
    skills_dir = directory or Path.home() / ".agents" / "skills"
    if not skills_dir.is_dir():
        return EMPTY_SKILL_CATALOG

    skills = []
    for child in sorted(skills_dir.iterdir(), key=lambda path: path.name):
        skill_file = child / "SKILL.md"
        if child.is_dir() and skill_file.is_file():
            skills.append(_read_skill(skill_file, child.name))
    return SkillCatalog(tuple(skills))


def _read_skill(path: Path, name: str) -> Skill:
    lines = path.read_text().splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"Skill is missing YAML frontmatter: {path}")

    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(
            f"Skill has unterminated YAML frontmatter: {path}"
        ) from error

    metadata = yaml.safe_load("\n".join(lines[1:closing])) or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"Skill frontmatter must be a mapping: {path}")

    description = metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"Skill is missing a description: {path}")

    body = "\n".join(lines[closing + 1 :]).strip()
    if not body:
        raise ValueError(f"Skill has no instructions: {path}")

    return Skill(
        name=name,
        description=description.strip(),
        body=body,
        disable_model_invocation=_read_bool(
            metadata,
            "disable-model-invocation",
            False,
            path,
        ),
        user_invocable=_read_bool(
            metadata,
            "user-invocable",
            True,
            path,
        ),
    )


def _read_bool(
    metadata: dict,
    key: str,
    default: bool,
    path: Path,
) -> bool:
    value = metadata.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"Skill {key} must be a boolean: {path}")
    return value
