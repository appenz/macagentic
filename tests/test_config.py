from pathlib import Path

from macagentic.config import load_config


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
    )
    home = tmp_path / "home"
    user_config = home / ".config" / "macagentic" / "config.toml"
    user_config.parent.mkdir(parents=True)
    user_config.write_text(
        'model = "openai/user-model"\n'
        'openai_api_key = "user-key"\n'
        'brave_api_key = "brave-user-key"\n'
        '[mounts]\n'
        'notes = "~/notes"\n'
    )
    monkeypatch.setenv("HOME", str(home))

    config = load_config(project)

    assert config.model == "openai/user-model"
    assert config.openai_api_key == "user-key"
    assert config.brave_api_key == "brave-user-key"
    assert config.custom_prompt == "Project instructions"
    assert config.mounts == {"notes": "~/notes"}
