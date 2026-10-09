# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "things.py>=1.0.1",
# ]
# ///
"""Small command-line interface for the Things to-do manager."""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Any


COMMANDS = {"new", "list", "complete", "done"}
COMMAND_HELP = """Things - CLI for the Things To-Do manager
Commands:
  things new "<to-do title>" [--area "<area or project>"] [--today]
  things list
  things complete <id>"""


def _things():
    import things

    return things


def _database():
    return _things().Database()


def _require_write_access() -> None:
    if not _things().token(database=_database()):
        raise RuntimeError(
            "Things URL auth token is unavailable. "
            "Enable Things URLs in Things settings first."
        )


def _open_url(command: str, uuid: str | None = None, **parameters: Any) -> None:
    _require_write_access()
    uri = _things().url(uuid=uuid, command=command, **parameters)
    result = subprocess.run(
        ["open", uri],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "open failed").strip()
        raise RuntimeError(f"Failed to open Things URL: {detail}")


def new_todo(title: str, area: str | None = None, today: bool = False) -> None:
    title = title.strip()
    if not title:
        raise ValueError("A to-do title is required.")
    parameters: dict[str, Any] = {"title": title}
    if area and area.strip():
        parameters["list"] = area.strip()
    if today:
        parameters["when"] = "today"
    _open_url("add", **parameters)
    details = []
    if "list" in parameters:
        details.append(f"in {parameters['list']}")
    if today:
        details.append("today")
    suffix = f" ({', '.join(details)})" if details else ""
    print(f"Created to-do: {title}{suffix}")


def list_todos() -> None:
    today = _things().today(database=_database())
    todos = [
        item
        for item in today
        if item.get("type") == "to-do"
        and item.get("status", "incomplete") == "incomplete"
    ]
    if not todos:
        print("No incomplete to-dos in Today.")
        return

    groups: dict[str, list[dict[str, Any]]] = {}
    for todo in todos:
        area = todo.get("area_title")
        project = todo.get("project_title")
        if area and project:
            group = f"Area: {area} / Project: {project}"
        elif project:
            group = f"Project: {project}"
        elif area:
            group = f"Area: {area}"
        else:
            group = "No Area or Project"
        groups.setdefault(group, []).append(todo)

    for index, (group, items) in enumerate(groups.items()):
        if index:
            print()
        print(group)
        for todo in items:
            print(f"  {todo['uuid']}\t{todo.get('title', '(untitled)')}")


def complete_todo(item_id: str) -> None:
    item_id = item_id.strip()
    item = _things().get(item_id, default=None, database=_database())
    if item is None:
        raise ValueError(f"No Things item found for ID '{item_id}'.")
    if item.get("type") != "to-do":
        raise ValueError(f"Things item '{item_id}' is not a to-do.")
    _open_url("update", uuid=item_id, completed=True)
    print(f"Completed to-do: {item.get('title', item_id)}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage Things to-dos")
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser("new", help="Create a to-do")
    new.add_argument("title", help="To-do title")
    new.add_argument("--area", help="Area or project name to file the to-do under")
    new.add_argument("--today", action="store_true", help="Schedule the to-do for Today")

    commands.add_parser("list", help="List Today's to-dos grouped by area/project")

    complete = commands.add_parser("complete", help="Mark a to-do completed")
    complete.add_argument("id", help="Things to-do ID")

    done = commands.add_parser("done", help=argparse.SUPPRESS)
    done.add_argument("id", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments or arguments[0] in {"-h", "--help"}:
        print(COMMAND_HELP)
        return 0
    if arguments[0] not in COMMANDS:
        print(f"Unknown command: {arguments[0]}", file=sys.stderr)
        print(COMMAND_HELP, file=sys.stderr)
        return 2

    args = parse_args(arguments)
    try:
        if args.command == "new":
            new_todo(args.title, args.area, args.today)
        elif args.command == "list":
            list_todos()
        elif args.command in {"complete", "done"}:
            complete_todo(args.id)
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
