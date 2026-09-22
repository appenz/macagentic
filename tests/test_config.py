from pathlib import Path

from macagentic.config import DEFAULT_MODELS, load_config


def test_user_config_overrides_project_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project_config = project / "config" / "config.toml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text(
        'custom_prompt = "Project instructions"\n'
        "[models]\n"
        'fast = "openai/project-fast"\n'
    )
    home = tmp_path / "home"
    user_config = home / ".config" / "macagentic" / "config.toml"
    user_config.parent.mkdir(parents=True)
    user_config.write_text(
        'openai_api_key = "user-key"\n'
        'anthropic_api_key = "anthropic-user-key"\n'
        'inception_api_key = "inception-user-key"\n'
        'brave_api_key = "brave-user-key"\n'
        "[models]\n"
        'slow = "openai/user-slow"\n'
        "[mounts]\n"
        'notes = "~/notes"\n'
    )
    monkeypatch.setenv("HOME", str(home))

    config = load_config(project)

    assert config.openai_api_key == "user-key"
    assert config.anthropic_api_key == "anthropic-user-key"
    assert config.inception_api_key == "inception-user-key"
    assert config.brave_api_key == "brave-user-key"
    assert config.custom_prompt == "Project instructions"
    assert config.mounts == {"notes": "~/notes"}
    assert config.models["fast"] == "openai/project-fast"
    assert config.models["medium"] == DEFAULT_MODELS["medium"]
    assert config.models["slow"] == "openai/user-slow"


def test_default_models(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)
    home = tmp_path / "home"
    (home / ".config" / "macagentic").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    config = load_config(project)

    assert config.models == DEFAULT_MODELS
    assert config.models["fast"] == "inception/mercury-2.5"
    assert config.models["slow"] == "anthropic/claude-fable-5-1"
    assert config.anthropic_api_key == ""
    assert config.inception_api_key == ""
