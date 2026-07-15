from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


TOOL_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("gwsx_tool", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
gwsx = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gwsx)


@pytest.fixture
def isolated_config(monkeypatch, tmp_path) -> Path:
    config = tmp_path / "config"
    working_directory = tmp_path / "working"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)
    monkeypatch.setenv(gwsx.CONFIG_ENV, str(config))
    return config


def test_add_account_creates_private_profile_and_runs_setup(
    monkeypatch,
    isolated_config,
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []
    monkeypatch.setattr(gwsx.shutil, "which", lambda _name: "/usr/local/bin/gws")

    def fake_run(command, *, env, check):
        calls.append((command, env))
        assert check is False
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(gwsx.subprocess, "run", fake_run)

    assert gwsx.main(["account", "add", "private"]) == 0

    profile = isolated_config / "accounts" / "private"
    assert profile.is_dir()
    assert profile.stat().st_mode & 0o777 == 0o700
    assert calls[0][0] == ["/usr/local/bin/gws", "auth", "setup"]
    assert calls[0][1][gwsx.GWS_CONFIG_ENV] == str(profile)


def test_add_account_refuses_existing_profile(
    monkeypatch,
    isolated_config,
    capsys,
) -> None:
    profile = isolated_config / "accounts" / "private"
    profile.mkdir(parents=True)
    monkeypatch.setattr(gwsx.shutil, "which", lambda _name: "/bin/gws")

    assert gwsx.main(["account", "add", "private"]) == 2
    assert "already exists" in capsys.readouterr().err


def test_list_accounts_reports_authentication_state(
    isolated_config,
    capsys,
) -> None:
    private = isolated_config / "accounts" / "private"
    work = isolated_config / "accounts" / "work"
    private.mkdir(parents=True)
    work.mkdir()
    (private / "credentials.enc").write_text("encrypted")

    assert gwsx.main(["account", "list"]) == 0
    assert capsys.readouterr().out == (
        "private\tauthenticated\n"
        "work\tsetup incomplete\n"
    )


def test_delete_account_removes_profile_and_local_credentials(
    isolated_config,
    capsys,
) -> None:
    profile = isolated_config / "accounts" / "private"
    profile.mkdir(parents=True)
    (profile / "credentials.enc").write_text("encrypted")
    (profile / "cache").mkdir()
    (profile / "cache" / "token").write_text("cached")

    assert gwsx.main(["account", "delete", "private"]) == 0
    assert not profile.exists()
    assert capsys.readouterr().out == (
        "Deleted account 'private' and its local credentials.\n"
    )


def test_delete_rejects_unknown_account(isolated_config, capsys) -> None:
    assert gwsx.main(["account", "delete", "private"]) == 2
    assert "Unknown account 'private'" in capsys.readouterr().err


def test_delete_refuses_symlink_profile(isolated_config, tmp_path, capsys) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "credentials.enc").write_text("keep")
    profile = isolated_config / "accounts" / "private"
    profile.parent.mkdir(parents=True)
    profile.symlink_to(target, target_is_directory=True)

    assert gwsx.main(["account", "delete", "private"]) == 2
    assert profile.is_symlink()
    assert (target / "credentials.enc").is_file()
    assert "profile is a symlink" in capsys.readouterr().err


def test_passthrough_preserves_arguments_and_selects_profile(
    monkeypatch,
    isolated_config,
) -> None:
    profile = isolated_config / "accounts" / "private"
    profile.mkdir(parents=True)
    monkeypatch.setattr(gwsx.shutil, "which", lambda _name: "/opt/bin/gws")
    monkeypatch.setenv("GOOGLE_WORKSPACE_CLI_TOKEN", "wrong-account-token")
    monkeypatch.setenv(
        "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE",
        "/tmp/wrong-account.json",
    )

    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(command, *, env, check):
        calls.append((command, env))
        assert check is False
        return subprocess.CompletedProcess(command, 3)

    monkeypatch.setattr(gwsx.subprocess, "run", fake_run)
    arguments = [
        "private",
        "drive",
        "files",
        "list",
        "--params",
        '{"pageSize": 5}',
        "--",
        "literal",
    ]

    assert gwsx.main(arguments) == 3
    command, env = calls[0]
    assert command == ["/opt/bin/gws", *arguments[1:]]
    assert env[gwsx.GWS_CONFIG_ENV] == str(profile)
    for name in gwsx.AUTH_OVERRIDE_ENVS:
        assert name not in env


def test_negative_child_status_maps_to_shell_signal_status(
    monkeypatch,
    isolated_config,
) -> None:
    profile = isolated_config / "accounts" / "private"
    profile.mkdir(parents=True)
    monkeypatch.setattr(gwsx.shutil, "which", lambda _name: "/bin/gws")
    monkeypatch.setattr(
        gwsx.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], -9),
    )

    assert gwsx.main(["private", "drive", "files", "list"]) == 137


@pytest.mark.parametrize("alias", ["../work", "Work", "private_account"])
def test_rejects_unsafe_or_reserved_aliases(
    alias,
    isolated_config,
    capsys,
) -> None:
    assert gwsx.main([alias, "drive", "files", "list"]) == 2
    assert "Account aliases" in capsys.readouterr().err


def test_rejects_reserved_account_alias(isolated_config, capsys) -> None:
    assert gwsx.main(["account", "add", "account"]) == 2
    assert "Account aliases" in capsys.readouterr().err


def test_unknown_account_is_actionable(isolated_config, capsys) -> None:
    assert gwsx.main(["private", "drive", "files", "list"]) == 2
    assert "gwsx account add private" in capsys.readouterr().err


def test_missing_gws_is_actionable(monkeypatch, isolated_config, capsys) -> None:
    (isolated_config / "accounts" / "private").mkdir(parents=True)
    monkeypatch.setattr(gwsx.shutil, "which", lambda _name: None)

    assert gwsx.main(["private", "drive", "files", "list"]) == 2
    assert "brew install googleworkspace-cli" in capsys.readouterr().err


def test_rejects_dotenv_auth_override(
    monkeypatch,
    isolated_config,
    capsys,
) -> None:
    (isolated_config / "accounts" / "private").mkdir(parents=True)
    Path(".env").write_text("GOOGLE_WORKSPACE_CLI_TOKEN=wrong-account\n")
    monkeypatch.setattr(gwsx.shutil, "which", lambda _name: "/bin/gws")

    assert gwsx.main(["private", "drive", "files", "list"]) == 2
    assert "nearest .env" in capsys.readouterr().err


def test_help_does_not_require_gws(isolated_config, capsys) -> None:
    assert gwsx.main([]) == 0
    assert "gwsx account add <alias>" in capsys.readouterr().out
