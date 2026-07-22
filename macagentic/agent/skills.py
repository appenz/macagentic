import re
from dataclasses import dataclass
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_USER_SKILLS_DIR = Path.home() / ".agents" / "skills"
DEFAULT_TOOLS_ROOT = PROJECT_ROOT / "tools"


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    disable_model_invocation: bool = False
    user_invocable: bool = True
    source: Path | None = None


@dataclass(frozen=True)
class SkillCatalog:
    skills: tuple[Skill, ...] = ()

    def render_prompt(self) -> str:
        return "\n".join(
            _render_skill(skill)
            for skill in self.skills
            if not skill.disable_model_invocation
        )

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
    skills_dir = directory or DEFAULT_USER_SKILLS_DIR
    return _load_skill_directories([skills_dir])


def load_available_skills(
    user_directory: Path | None = None,
    tools_root: Path | None = None,
) -> SkillCatalog:
    tools_directory = tools_root or DEFAULT_TOOLS_ROOT
    directories = []
    if tools_directory.is_dir():
        directories.extend(
            skills_dir
            for tool in sorted(tools_directory.iterdir(), key=lambda path: path.name)
            if tool.is_dir() and (skills_dir := tool / "skills").is_dir()
        )
    directories.append(user_directory or DEFAULT_USER_SKILLS_DIR)
    return _load_skill_directories(directories)


def _load_skill_directories(directories: list[Path]) -> SkillCatalog:
    skills: dict[str, Skill] = {}
    for skills_dir in directories:
        if not skills_dir.is_dir():
            continue
        for child in sorted(skills_dir.iterdir(), key=lambda path: path.name):
            skill_file = child / "SKILL.md"
            if not child.is_dir() or not skill_file.is_file():
                continue
            skill = _read_skill(skill_file, child.name)
            if existing := skills.get(skill.name):
                raise ValueError(
                    f"Duplicate skill '{skill.name}': "
                    f"{existing.source} and {skill.source}"
                )
            skills[skill.name] = skill

    if not skills:
        return EMPTY_SKILL_CATALOG
    return SkillCatalog(tuple(skills[name] for name in sorted(skills)))


def _render_skill(skill: Skill) -> str:
    return f"{skill.name} - {skill.description}"


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
        source=path.resolve(),
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
