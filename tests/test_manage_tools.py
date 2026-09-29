from pathlib import Path

import pytest

from scripts.manage_tools import (
    TOOLS_ROOT,
    ToolError,
    discover_tools,
    install_tools,
    uninstall_tools,
    write_prompt,
)


def make_tool(tools_root: Path, name: str) -> None:
    directory = tools_root / name
    directory.mkdir(parents=True)
    launcher = directory / name
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)
    (directory / "main.py").write_text("print('ok')\n")
    (directory / "PROMPT.md").write_text(f"Use {name}.\n")


def test_discovers_tools_in_name_order(tmp_path) -> None:
    tools_root = tmp_path / "tools"
    make_tool(tools_root, "weather")
    make_tool(tools_root, "things")

    assert [tool.name for tool in discover_tools(tools_root)] == [
        "things",
        "weather",
    ]


def test_install_and_uninstall_manage_only_tool_symlinks(tmp_path) -> None:
    tools_root = tmp_path / "tools"
    bin_dir = tmp_path / "bin"
    make_tool(tools_root, "things")
    unrelated = tmp_path / "unrelated"
    unrelated.write_text("")
    bin_dir.mkdir()
    (bin_dir / "other").symlink_to(unrelated)

    tools = discover_tools(tools_root)
    install_tools(tools, bin_dir)
    assert (bin_dir / "things").resolve() == tools[0].launcher.resolve()

    uninstall_tools(tools_root, bin_dir)
    assert not (bin_dir / "things").exists()
    assert (bin_dir / "other").is_symlink()


def test_install_refuses_to_replace_existing_command(tmp_path) -> None:
    tools_root = tmp_path / "tools"
    bin_dir = tmp_path / "bin"
    make_tool(tools_root, "things")
    bin_dir.mkdir()
    (bin_dir / "things").write_text("unrelated")

    with pytest.raises(ToolError, match="Refusing to replace"):
        install_tools(discover_tools(tools_root), bin_dir)


def test_install_updates_managed_symlink_from_another_checkout(tmp_path) -> None:
    old_root = tmp_path / "old" / "tools"
    new_root = tmp_path / "new" / "tools"
    bin_dir = tmp_path / "bin"
    make_tool(old_root, "things")
    make_tool(new_root, "things")
    bin_dir.mkdir()
    (bin_dir / "things").symlink_to((old_root / "things" / "things").resolve())

    tools = discover_tools(new_root)
    install_tools(tools, bin_dir)

    assert (bin_dir / "things").resolve() == tools[0].launcher.resolve()


def test_writes_aggregated_prompt(tmp_path) -> None:
    tools_root = tmp_path / "tools"
    make_tool(tools_root, "weather")
    make_tool(tools_root, "things")
    output = tmp_path / ".build" / "tools.md"

    write_prompt(discover_tools(tools_root), output)

    assert output.read_text() == "Use things.\n\nUse weather.\n"


def test_repo_tools_prompt_is_compact(tmp_path) -> None:
    output = tmp_path / "tools.md"
    write_prompt(discover_tools(TOOLS_ROOT), output)
    text = output.read_text()

    assert not any(line.startswith("#") for line in text.splitlines())
