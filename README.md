# macAgentic

A native macOS Cocoa UI for [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent), written entirely in Python with [PyObjC](https://pyobjc.readthedocs.io/).
It renders Markdown and mathematical formulas for polished agent responses.
Model selection and tabs make it easy to switch models and manage multiple conversations.

![macAgentic screenshot](docs/screenshot.png)

## Installation

Use [uv](https://docs.astral.sh/uv/) to install dependencies and launch the UI:

```sh
uv sync
uv run python -m macagentic --ui
```

## Cursor mobile and non-macOS development

Cursor mobile can drive Cursor cloud agents for headless development and tests.
Those agents do not provide a macOS desktop session, so they cannot exercise the
native Cocoa UI directly. Use them for the core harness, tools, config, usage,
transcript, and Markdown-free tests:

```sh
make test
make check-tools
```

The native UI remains macOS-only. Run UI-specific checks from a macOS machine:

```sh
make test-ui
make debug-render QUERY="Show a Markdown table"
```

Agent tools live in `tools/<name>/` with a same-named shell launcher, a
`main.py` implementation, `PROMPT.md`, and colocated tests. `make install-tools` creates
safe per-user symlinks in `~/.local/bin`; ensure that directory is on `PATH`.
Remove this project's links with `make uninstall-tools`.

## Tools

macAgentic includes a small set of command-line tools for common agent tasks:

- `gwsx` — access Google Workspace with explicit accounts
- `noteheader` — create meeting-note headers
- `things` — manage Things to-dos
- `websearch` — search the web with Brave Search

## Configuration

Defaults live in `config/config.toml`; override them per user in `~/.config/macagentic/config.toml`.
You can configure:

- `model` — default model
- `models` — fast, medium, and slow model choices
- `openai_api_key` and `brave_api_key` — service credentials
- `custom_prompt` — additional system instructions
- `mounts` — directories exposed to agent workspaces

## Command-line flags

Pass these options when launching `python -m macagentic`:

- `--task-file PATH` / `--spec PATH`
- `--model MODEL`
- `--instructions PATH`
- `--tool-instructions PATH`
- `--ui`
- `--tooloutput`
- `--screenshot PATH`
- `-h` / `--help`

An initial task may also be passed as a positional argument.

## License

macAgentic is licensed under the Apache License 2.0.
