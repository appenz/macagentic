"""Discover, install, and document self-contained agent tools."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = PROJECT_ROOT / "tools"
DEFAULT_BIN_DIR = Path.home() / ".local" / "bin"
TOOL_NAME = re.compile(r"^[a-z][a-z0-9-]*$")


class ToolError(RuntimeError):
    """Raised when a tool does not satisfy the repository contract."""


@dataclass(frozen=True)
class Tool:
    name: str
    launcher: Path
    implementation: Path
    prompt: Path


def discover_tools(tools_root: Path = TOOLS_ROOT) -> list[Tool]:
    tools: list[Tool] = []
    if not tools_root.is_dir():
        return tools

    for directory in sorted(tools_root.iterdir()):
        if not directory.is_dir() or directory.name.startswith("."):
            continue

        name = directory.name
        if not TOOL_NAME.fullmatch(name):
            raise ToolError(f"Invalid tool directory name: {name}")

        tool = Tool(
            name=name,
            launcher=directory / name,
            implementation=directory / "main.py",
            prompt=directory / "PROMPT.md",
        )
        missing = [
            path.name
            for path in (tool.launcher, tool.implementation, tool.prompt)
            if not path.is_file()
        ]
        if missing:
            raise ToolError(f"Tool {name} is missing: {', '.join(missing)}")
        if not os.access(tool.launcher, os.X_OK):
            raise ToolError(f"Tool launcher is not executable: {tool.launcher}")
        if not tool.prompt.read_text().strip():
            raise ToolError(f"Tool prompt is empty: {tool.prompt}")
        tools.append(tool)

    return tools


def _resolved_symlink(path: Path) -> Path:
    target = Path(os.readlink(path))
    if not target.is_absolute():
        target = path.parent / target
    return target.resolve()


def install_tools(tools: list[Tool], bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    for tool in tools:
        destination = bin_dir / tool.name
        target = tool.launcher.resolve()
        if destination.is_symlink() and _resolved_symlink(destination) == target:
            print(f"already installed: {destination}")
            continue
        if destination.exists() or destination.is_symlink():
            raise ToolError(f"Refusing to replace existing path: {destination}")
        destination.symlink_to(target)
        print(f"installed: {destination} -> {target}")


def uninstall_tools(tools_root: Path, bin_dir: Path) -> None:
    if not bin_dir.is_dir():
        return

    tools_root = tools_root.resolve()
    for destination in sorted(bin_dir.iterdir()):
        if not destination.is_symlink():
            continue
        target = _resolved_symlink(destination)
        try:
            relative = target.relative_to(tools_root)
        except ValueError:
            continue
        if (
            len(relative.parts) == 2
            and relative.parts[0] == relative.parts[1]
            and destination.name == relative.parts[0]
        ):
            destination.unlink()
            print(f"uninstalled: {destination}")


def write_prompt(tools: list[Tool], output: Path) -> None:
    sections = ["# Available Tools"]
    for tool in tools:
        sections.append(f"## `{tool.name}`\n\n{tool.prompt.read_text().strip()}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n\n".join(sections) + "\n")
    print(f"wrote: {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bin-dir",
        type=Path,
        default=DEFAULT_BIN_DIR,
        help="Per-user command directory (default: ~/.local/bin)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check")
    subparsers.add_parser("install")
    subparsers.add_parser("uninstall")
    prompt = subparsers.add_parser("prompt")
    prompt.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "uninstall":
            uninstall_tools(TOOLS_ROOT, args.bin_dir.expanduser())
            return 0

        tools = discover_tools()
        if args.command == "check":
            for tool in tools:
                print(f"valid: {tool.name}")
        elif args.command == "install":
            install_tools(tools, args.bin_dir.expanduser())
        elif args.command == "prompt":
            write_prompt(tools, args.output)
    except ToolError as error:
        print(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
