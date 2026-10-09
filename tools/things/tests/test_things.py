from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


TOOL_PATH = Path(__file__).parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("things_tool", TOOL_PATH)
assert SPEC and SPEC.loader
things_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(things_tool)


class FakeThings:
    def __init__(self) -> None:
        self.urls = []
        self.items = [
            {
                "uuid": "todo-1",
                "title": "Buy milk",
                "type": "to-do",
                "status": "incomplete",
                "area_title": "Personal",
            },
            {
                "uuid": "todo-2",
                "title": "Call Sam",
                "type": "to-do",
                "status": "incomplete",
                "area_title": "Work",
                "project_title": "Launch",
            },
        ]

    @staticmethod
    def Database():
        return object()

    @staticmethod
    def token(**_kwargs):
        return "token"

    def url(self, **kwargs):
        self.urls.append(kwargs)
        return "things:///test"

    def today(self, **_kwargs):
        return self.items

    def get(self, item_id, **_kwargs):
        return next(
            (item for item in self.items if item["uuid"] == item_id),
            None,
        )


@pytest.fixture
def fake_things(monkeypatch):
    fake = FakeThings()
    monkeypatch.setitem(sys.modules, "things", fake)
    monkeypatch.setattr(
        things_tool.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
        ),
    )
    return fake


def test_new_creates_todo(fake_things, capsys) -> None:
    assert things_tool.main(["new", "Buy tea"]) == 0

    assert fake_things.urls == [
        {"uuid": None, "command": "add", "title": "Buy tea"}
    ]
    assert capsys.readouterr().out == "Created to-do: Buy tea\n"


def test_list_prints_ids_and_titles(fake_things, capsys) -> None:
    fake_things.items.extend(
        [
            {
                "uuid": "done-1",
                "title": "Already done",
                "type": "to-do",
                "status": "completed",
            },
            {
                "uuid": "project-1",
                "title": "Not a to-do",
                "type": "project",
                "status": "incomplete",
            },
        ]
    )

    assert things_tool.main(["list"]) == 0

    assert capsys.readouterr().out == (
        "Area: Personal\n"
        "  todo-1\tBuy milk\n"
        "\n"
        "Area: Work / Project: Launch\n"
        "  todo-2\tCall Sam\n"
    )


def test_complete_completes_todo(fake_things, capsys) -> None:
    assert things_tool.main(["complete", "todo-2"]) == 0

    assert fake_things.urls == [
        {
            "uuid": "todo-2",
            "command": "update",
            "completed": True,
        }
    ]
    assert capsys.readouterr().out == "Completed to-do: Call Sam\n"


def test_done_rejects_unknown_id(fake_things, capsys) -> None:
    assert things_tool.main(["done", "missing"]) == 1

    assert "No Things item found" in capsys.readouterr().err


def test_no_command_prints_concise_help(capsys) -> None:
    assert things_tool.main([]) == 0

    assert capsys.readouterr().out == (
        "Things - CLI for the Things To-Do manager\n"
        "Commands:\n"
        '  things new "<to-do title>" [--area "<area or project>"] [--today]\n'
        "  things list\n"
        "  things complete <id>\n"
    )


def test_unknown_command_prints_concise_help(capsys) -> None:
    assert things_tool.main(["wat"]) == 2

    assert capsys.readouterr().err == (
        "Unknown command: wat\n"
        "Things - CLI for the Things To-Do manager\n"
        "Commands:\n"
        '  things new "<to-do title>" [--area "<area or project>"] [--today]\n'
        "  things list\n"
        "  things complete <id>\n"
    )


def test_done_remains_an_alias(fake_things) -> None:
    assert things_tool.main(["done", "todo-1"]) == 0
