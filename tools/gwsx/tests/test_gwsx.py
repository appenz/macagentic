from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


TOOL_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("gwsx_tool", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
gwsx = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gwsx)


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _message(
    message_id: str,
    *,
    internal_date: str,
    labels: list[str],
    subject: str = "Subject",
    body: str = "body",
    mime: str = "text/plain",
    in_reply_to: str | None = None,
) -> dict:
    headers = [
        {"name": "Subject", "value": subject},
        {"name": "From", "value": "sender@example.com"},
        {"name": "To", "value": "me@example.com"},
        {"name": "Date", "value": "Fri, 11 Sep 2026 12:00:00 +0000"},
    ]
    if in_reply_to is not None:
        headers.append({"name": "In-Reply-To", "value": in_reply_to})
    return {
        "id": message_id,
        "threadId": "thread-1",
        "internalDate": internal_date,
        "labelIds": labels,
        "payload": {
            "mimeType": mime,
            "headers": headers,
            "body": {"data": _b64(body)},
        },
    }


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
    help_text = capsys.readouterr().out
    assert "gwsx account add <alias>" in help_text
    assert "gmail +active-threads" in help_text


def test_select_active_messages_from_oldest_unread() -> None:
    messages = [
        _message("1", internal_date="1", labels=["INBOX"]),
        _message("2", internal_date="2", labels=["INBOX", "UNREAD"]),
        _message("3", internal_date="3", labels=["SENT"]),
        _message("4", internal_date="4", labels=["INBOX", "UNREAD"]),
        _message("5", internal_date="5", labels=["SENT"]),
    ]
    selected = gwsx.select_active_messages(messages, include_all=False)
    assert [message["id"] for message in selected] == ["2", "3", "4", "5"]


def test_select_active_messages_falls_back_to_newest() -> None:
    messages = [
        _message("1", internal_date="1", labels=["INBOX"]),
        _message("2", internal_date="2", labels=["SENT"]),
    ]
    selected = gwsx.select_active_messages(messages, include_all=False)
    assert [message["id"] for message in selected] == ["2"]


def test_build_thread_view_truncates_body_and_preserves_reply_linkage() -> None:
    thread = {
        "id": "thread-1",
        "messages": [
            _message(
                "m1",
                internal_date="10",
                labels=["INBOX", "UNREAD"],
                body="Hello world",
                in_reply_to="<parent@example.com>",
            )
        ],
    }
    view = gwsx.build_thread_view(
        thread,
        include_all=False,
        max_body_chars=5,
        max_thread_chars=100,
    )
    message = view["messages"][0]
    assert view["selection"] == "oldest-unread-and-later"
    assert message["body"] == "Hello"
    assert message["bodyTruncated"] is True
    assert message["bodyChars"] == 11
    assert message["inReplyTo"] == "<parent@example.com>"


def test_thread_char_budget_preserves_newest_messages() -> None:
    thread = {
        "id": "thread-1",
        "messages": [
            _message("1", internal_date="1", labels=["INBOX", "UNREAD"], body="AAAA"),
            _message("2", internal_date="2", labels=["INBOX"], body="BBBB"),
            _message("3", internal_date="3", labels=["SENT"], body="CCCC"),
        ],
    }
    view = gwsx.build_thread_view(
        thread,
        include_all=True,
        max_body_chars=100,
        max_thread_chars=6,
    )
    bodies = [message["body"] for message in view["messages"]]
    assert bodies == ["", "BB", "CCCC"]
    assert view["messages"][0]["omittedForBudget"] is True
    assert view["messages"][1]["bodyTruncated"] is True


def test_html_body_is_converted_and_attachments_are_skipped() -> None:
    html_body = _b64("<p>Hello <b>there</b></p><script>bad()</script>")
    attachment = _b64("secret-bytes")
    message = {
        "id": "m1",
        "threadId": "thread-1",
        "internalDate": "10",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "Subject", "value": "HTML"}],
            "parts": [
                {
                    "mimeType": "text/html",
                    "filename": "",
                    "body": {"data": html_body},
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "file.pdf",
                    "body": {"data": attachment},
                },
            ],
        },
    }
    normalized = gwsx.normalize_message(message, max_body_chars=100)
    assert "Hello" in normalized["body"]
    assert "there" in normalized["body"]
    assert "bad()" not in normalized["body"]
    assert "secret-bytes" not in normalized["body"]


def test_active_threads_command_outputs_tsv(
    monkeypatch,
    isolated_config,
    capsys,
) -> None:
    profile = isolated_config / "accounts" / "private"
    profile.mkdir(parents=True)
    monkeypatch.setattr(gwsx.shutil, "which", lambda _name: "/bin/gws")

    def fake_invoke(arguments, profile_path, *, executable=None):
        assert profile_path == profile
        assert arguments[3] == "list"
        params = json.loads(arguments[arguments.index("--params") + 1])
        assert params["fields"] == "threads(id,snippet)"
        assert params["maxResults"] == 10
        return {
            "threads": [
                {"id": "t1", "snippet": "Short preview"},
                {"id": "t2", "snippet": "X" * 60},
                {"id": "t3"},
            ]
        }

    monkeypatch.setattr(gwsx, "invoke_gws_json", fake_invoke)
    assert gwsx.main(["private", "gmail", "+active-threads", "--max", "10"]) == 0
    assert capsys.readouterr().out == (
        "t1\tShort preview\n"
        f"t2\t{'X' * 60}\n"
        "t3\t(no snippet)\n"
    )


def test_thread_command_defaults_to_text_selection(
    monkeypatch,
    isolated_config,
    capsys,
) -> None:
    profile = isolated_config / "accounts" / "private"
    profile.mkdir(parents=True)
    monkeypatch.setattr(gwsx.shutil, "which", lambda _name: "/bin/gws")

    def fake_invoke(arguments, profile_path, *, executable=None):
        return {
            "id": "thread-1",
            "messages": [
                _message("1", internal_date="1", labels=["INBOX"], body="old"),
                _message(
                    "2",
                    internal_date="2",
                    labels=["INBOX", "UNREAD"],
                    body="new unread",
                ),
                _message("3", internal_date="3", labels=["SENT"], body="reply"),
            ],
        }

    monkeypatch.setattr(gwsx, "invoke_gws_json", fake_invoke)
    assert gwsx.main(["private", "gmail", "+thread", "--id", "thread-1"]) == 0
    output = capsys.readouterr().out
    assert "threadId: thread-1" in output
    assert "selection: oldest-unread-and-later" in output
    assert "id: 2" in output
    assert "id: 3" in output
    assert "id: 1" not in output
    assert "new unread" in output
    assert "reply" in output
