# Agent

## Overview

`Agent` owns one conversation with the user. It contains the model-facing
conversation, the agentic loop, tool execution, usage accounting, and
cooperative interruption.

`Agent` may hold an optional reference to the current UI, but may use it only
to call `ui.update()`. The UI may call only `agent.run_turn(request)`,
`agent.interrupt()`, `agent.set_model(model_name)`, and
`agent.set_model_tier(tier)`.

## Agent Class

```python
class Agent:
    # Dependencies
    id: int
    root: Path
    model: ResponseModel
    model_presets: dict[str, str]
    tool_runner: ShellEnvironment
    skill_catalog: SkillCatalog

    # Conversation state
    messages: list[dict]
    conversation_log: ConversationLog
    usage: UsageTracker

    # Execution
    interrupted: threading.Event

    # UI
    ui: UI | None

    @property
    def model_name(self) -> str: ...

    def update_ui(self) -> None: ...

    def set_model(self, model_name: str) -> None: ...

    def set_model_tier(self, tier: str) -> None: ...

    def run_turn(self, request: str) -> None: ...

    def interrupt(self) -> None: ...
```



## Fields

- `id`: Process-local positive integer assigned by `MacAgenticApp`.
- `root`: Clean working directory at `~/.tmpagent/<id>`.
- `model`: mini-SWE-agent model adapter used for model calls and tool messages.
- `model_presets`: Mapping of `fast` / `medium` / `slow` to LiteLLM model names.
- `tool_runner`: Local shell-command executor used for tool calls and interruption.
- `skill_catalog`: Immutable skill definitions used in the prompt and slash-command expansion.
- `messages`: Ordered, structured context sent to the model.
- `conversation_log`: Ordered, append-only application ledger containing messages and additional agent events.
- `usage`: Cumulative model token and cost tracking.
- `interrupted`: Thread-safe signal that cancels the current turn.
- `ui`: Optional current UI, used only to request an update.
- `model_name`: Read-only model identifier exposed by `model`.



## Dependencies

mini-SWE-agent provides the model and environment foundations; macAgentic
owns its smaller agent loop rather than using `DefaultAgent`. Model calls
use LiteLLM's native Responses API.

## Filesystem

An `Agent` reuses `~/.tmpagent/<id>` when present, otherwise creates it, and
uses it for shell commands. `$AGENT_ROOT` contains its absolute path;
`~` remains the user's normal home directory. The root contains a `skills/`
symlink farm plus the user mounts configured in `[mounts]`. Model-facing paths
remain relative to the agent root.

## Agent Loop

User input → model-tier slash commands → skill expansion → model call → tool
execution → observation → repeat or return.

`/fast`, `/medium`, and `/slow` are stripped from user input like skill
commands. The last matching tier overwrites the agent's model string using
`model_presets`. A `model_switch` conversation-log event is appended only for
these slash commands (not for Cocoa menu or keyboard shortcuts). If only tier
commands remain, the turn returns without querying the model.

## Data Invariant

Every model message is copied into `conversation_log` in order. Additional
agent events, such as original unexpanded input, are interleaved where they
occur.

## Interruption

`run_turn()` clears `interrupted`, checks it around model and tool work, and
returns when it is set. `interrupt()` sets the event and stops active tools.
Model calls run on daemon workers; a late result remains local and is
discarded. Only one turn runs at a time, and the next turn starts after the
interrupted turn returns.

## Files

- `macagentic/agent/agent.py`: `Agent`, prompt construction, and agent loop.
- `macagentic/agent/model.py`: mini-SWE-agent Responses API adapter.
- `macagentic/agent/conversation_log.py`: append-only application ledger.
- `macagentic/agent/shell.py`: interruptible local shell execution.
- `macagentic/agent/skills.py`: skill discovery and expansion.
- `macagentic/agent/usage.py`: token and cost tracking.
