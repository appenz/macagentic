# macAgentic Overview

**IMPORTANT:** Before writing code or making architecture decisions, read this
overview and every task-relevant spec below. Read `testing.md` before visual UI
work.

macAgentic is a macOS-native agent written in Python. It provides a terminal interface and a multi-tab Cocoa interface over the swe-agent-mini harness. The only tool is bash. Models are invoked via LiteLLM.

## Application and Configuration

`MacAgenticApp` is the single global application object. It owns the effective
configuration, model presets, skills, mounts, and process-level options, and it
creates identically configured agents with monotonically increasing IDs.

Project TOML defaults are overlaid by user configuration and then command-line
options. Each agent receives its own model selection, conversation, usage
tracker, and reusable root at `~/.tmpagent/<id>`.

## Agent

`Agent` owns one conversation and the complete agentic loop:

1. Record and expand user input.
2. Query the selected model through LiteLLM's Responses API.
3. Execute requested shell tools.
4. Append tool observations and repeat, or return the final response.

`Agent.messages` is the model-facing conversation.
`Agent.conversation_log` is an ordered, append-only application ledger. Every
model message is copied into it in order, with UI-relevant events such as the
original unexpanded input, model switches, tool executions, and interruptions
interleaved.

The agent supports cooperative interruption and cumulative provider-reported
token and cost accounting. Model selection is per agent and may change through
the UI or `/fast`, `/medium`, and `/slow`.

## Filesystem, Tools, and Skills

An agent's shell runs from its root with `$AGENT_ROOT` set. The root contains
private scratch space, configured user directories exposed through symlinks,
and links to discovered skills. `~` continues to mean the user's home
directory.

The model has one native `bash` tool. Additional tools are ordinary shell
commands documented in the system prompt. Image and PDF reads use the
namespaced `macagentic-read-file` command, which stages bounded immutable
snapshots under `$AGENT_ROOT/context/` for multimodal model input.

Skills are discovered once at startup, listed in the system prompt, exposed
under `skills/`, and optionally expanded from user slash commands.

## User Interfaces

The two interfaces are `CommandLineUI` and `MacAgenticUI`. All presentation
state and behavior lives under `macagentic/ui/`; `Agent` imports no UI
implementation and may not read UI state.

The UI may read agent state, including the conversation log and usage. Calls
across the boundary are limited to:

- `agent.ui.update()` to request a refresh.
- `ui → agent.run_turn(request)` to run a request.
- `ui → agent.interrupt()` to stop current work.
- `ui → agent.set_model(...)` or `set_model_tier(...)` to change models.

The Cocoa UI gives each tab an independent agent and persistent native views.
Agent turns and lightweight title/description model calls run asynchronously;
only AppKit's main thread mutates UI state. Open tabs and conversations are
restored for the same workspace across normal application restarts.

The Cocoa transcript renders native Markdown, collapsible blocks, tables, links,
and rasterized LaTeX while leaving the conversation log unchanged. The CLI
projects that same log as plain text.

## Specs

- `overview.md` — System boundaries and architectural index.
- `agent.md` — Agent state, model loop, filesystem, and interruption.
- `app.md` — Global application configuration and agent creation.
- `config.md` — TOML, model presets, mounts, and CLI precedence.
- `image_pdf_handling.md` — Staging images and PDFs for model context.
- `markdown_rendering.md` — Native Markdown, math, copy, and paste behavior.
- `skills.md` — Skill discovery, exposure, and slash-command expansion.
- `testing.md` — Screenshot and manual visual-testing workflows.
- `ui.md` — CLI and Cocoa ownership, tabs, updates, and persistence.
- `usage.md` — Token, cache, cost accounting, and presentation.
- `future_fusefs.md` — Unimplemented FUSE workspace proposal; ignore for current work.

