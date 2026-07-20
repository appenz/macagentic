# Agent

## Overview

`Agent` owns one conversation with the user. It contains the model-facing
conversation, the agentic loop, tool execution, usage accounting, and
cooperative interruption.

`Agent` may hold an optional reference to the current UI, but may use it only
to call `ui.update()`. The UI may call only `agent.run_turn(request)` and
`agent.interrupt()`.

## Agent Class

```python
class Agent:
    # Dependencies
    workspace: Path
    model: ResponseModel
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

    def run_turn(self, request: str) -> None: ...

    def interrupt(self) -> None: ...
```



## Fields

- `workspace`: Working directory used for local tool execution.
- `model`: mini-SWE-agent model adapter used for model calls and tool messages.
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

## Agent Loop

User input → skill expansion → model call → tool execution → observation →
repeat or return.

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