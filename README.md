# macAgentic

An agent harness powered by [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent).

Run in the terminal:

```sh
make install-tools
make run
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

### Testing

Core tests (run anywhere):

```sh
make test            # all non-UI tests
make check-tools     # validate tool layout
make test-tools      # only tool tests
```

Hardware tests (macOS only, requires real screencapture/osascript):

```sh
uv run pytest -m hardware -v
```

End-to-end vision model test (sends a real screenshot to a local vision model):

```sh
# Default: fast-qwen on 192.168.1.157
uv run pytest tools/ui/tests/test_vision_pipeline.py -m hardware -v

# Or point at deep-qwen:
uv run pytest tools/ui/tests/test_vision_pipeline.py -m hardware -v \
    --vision-url http://192.168.1.161:8081/v1
```

Agent tools live in `tools/<name>/` with a same-named shell launcher, a
`main.py` implementation, `PROMPT.md`, and colocated tests. `make install-tools` creates
safe per-user symlinks in `~/.local/bin`; ensure that directory is on `PATH`.
Remove this project's links with `make uninstall-tools`.

### Available Tools

**`ui` — macOS UI automation (screenshot, click, type)**

Captures screenshots and sends them to the model as proper image content when
using a vision-capable model. Requires `~/.local/bin` on `PATH`:

```sh
make install-tools   # create symlinks in ~/.local/bin
ui screenshot         # capture screen (output sent to model as image)
ui click 500 300      # click at coordinates
ui type "hello"       # send keystrokes
```

**`things` — macOS Things app integration.**

`make run` and `make runui` regenerate `.build/tools.md` from each tool's
`PROMPT.md` and append it to the system prompt. They do not install tools.
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

Append custom system instructions without changing the default prompt:

```sh
make run ARGS="--instructions path/to/instructions.md"
make runui ARGS="--instructions path/to/instructions.md"
```

The base prompt lives in `macagentic/agent/prompts/default.md`. With no
`--instructions` argument, loading it preserves the existing behavior.

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
after every model call. UI tabs show the same cumulative usage in the top bar.
