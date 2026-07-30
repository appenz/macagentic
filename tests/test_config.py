from pathlib import Path

from macagentic.config import DEFAULT_MODELS, DEFAULT_MODEL, load_config


def test_user_config_overrides_project_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project_config = project / "config" / "config.toml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text(
        'model = "openai/project-model"\n'
        'custom_prompt = "Project instructions"\n'
        "[models]\n"
        'fast = "openai/project-fast"\n'
    )
    home = tmp_path / "home"
    user_config = home / ".config" / "macagentic" / "config.toml"
    user_config.parent.mkdir(parents=True)
    user_config.write_text(
        'model = "openai/user-model"\n'
        'openai_api_key = "user-key"\n'
        'brave_api_key = "brave-user-key"\n'
        "[models]\n"
        'slow = "openai/user-slow"\n'
        "[mounts]\n"
        'notes = "~/notes"\n'
    )
    monkeypatch.setenv("HOME", str(home))

    config = load_config(project)

    assert config.model == "openai/user-model"
    assert config.openai_api_key == "user-key"
    assert config.brave_api_key == "brave-user-key"
    assert config.custom_prompt == "Project instructions"
    assert config.mounts == {"notes": "~/notes"}
    assert config.models["fast"] == "openai/project-fast"
    assert config.models["medium"] == DEFAULT_MODELS["medium"]
    assert config.models["slow"] == "openai/user-slow"


def test_default_models_match_medium_default(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)
    home = tmp_path / "home"
    (home / ".config" / "macagentic").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    config = load_config(project)

    assert config.model == DEFAULT_MODEL
    assert config.models == DEFAULT_MODELS
