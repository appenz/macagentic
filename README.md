# macAgentic

An agent harness powered by [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent).

Run in the terminal:

```sh
make install-tools
make run
```

Agent tools live in `tools/<name>/` with a same-named shell launcher, a
`main.py` implementation, `PROMPT.md`, and colocated tests. `make install-tools` creates
safe per-user symlinks in `~/.local/bin`; ensure that directory is on `PATH`.
Remove this project's links with `make uninstall-tools`.

`make run` and `make runui` regenerate `.build/tools.md` from each tool's
`PROMPT.md` and substitute it into the `{{TOOLS}}` placeholder in the system
prompt (`# Available Tools` lives in the prompt file). Custom instructions
fill `{{CUSTOM_INSTRUCTIONS}}`. They do not install tools.
Validate tool layouts with `make check-tools` and run only tool tests with
`make test-tools`.

The harness maintains one conversation and alternates between `You:` and
`Agent:` turns. The agent can run bash commands when needed, but answers simple
questions directly. Press Control-C to interrupt the current run and return to
the prompt; enter `/exit` or `/quit` to stop.

Start the optional native PyObjC UI:

```sh
make runui
# equivalent to:
uv run --frozen python -m macagentic --ui
```

The UI is a passive renderer over the agent's in-memory Markdown output. The
agent does not depend on the UI, and the headless path does not import PyObjC.
Press Option-Space globally to hide or reopen the UI.

Pass `--tooloutput` to either mode to include bash commands and their output:

```sh
make run ARGS="--tooloutput"
make runui ARGS="--tooloutput"
```

Run with an inline task or a task file from `tasks/`:

```sh
make run ARGS='"Fix the failing tests"'
make run ARGS="--task-file tasks/example.md"
make runui ARGS="--task-file tasks/example.md"
```

Fill `{{CUSTOM_INSTRUCTIONS}}` in the default prompt without editing the file:

```sh
make run ARGS="--instructions path/to/instructions.md"
make runui ARGS="--instructions path/to/instructions.md"
```

The base prompt lives in `macagentic/agent/prompts/default.md`. With no
`--instructions` argument, `{{CUSTOM_INSTRUCTIONS}}` is left empty.

Project defaults are loaded from `config/config.toml`. Override any value in
`~/.config/macagentic/config.toml`; user values win recursively. Supported
values are `model`, `openai_api_key`, and `custom_prompt`.

Capture a completed UI render for debugging:

```sh
make debug-render QUERY="Show a Markdown table"
```

Use `--model` for a one-run model override. `OPENAI_API_KEY` in `.env` remains
supported when `openai_api_key` is not set in TOML.

Models use LiteLLM's native Responses API. Configure ordinary provider model
IDs such as `openai/gpt-5.6-terra`; do not add an `openai/responses/` bridge
prefix. Terminal runs print cumulative input, cache, output, and cost usage
once after each turn. UI tabs show live cumulative usage in the top bar.
