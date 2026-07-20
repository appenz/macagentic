# User Interface

## Overview

`Agent.ui` has three valid options:

- `None`: no UI; `Agent.run_turn()` returns and the batch process exits.
- `CommandLineUI`: one interactive agent, implemented in `macagentic/ui/cli.py`.
- `MacAgenticUI`: the full multi-tab Cocoa application, implemented in `macagentic/ui/core.py`.

All presentation behavior and state lives under `macagentic/ui/`. An `Agent`
owns no UI state and imports no UI implementation. The UI may read agent state,
but the only cross-boundary calls are the ones explicitly allowed in
`overview.md`. The UI renders `Agent.conversation_log` and may read other
fields such as usage, cost, and model.

## Command Line

`CommandLineUI` owns one `Agent` and all terminal interaction: the prompt loop,
output projection, usage display, `/exit`, and signal handling. It creates the
agent with `ui=self`; `update()` reads and prints new conversation-log entries.

```python
class CommandLineUI:
    agent: Agent
    log_render_index: int
    show_tool_output: bool
    update_lock: threading.Lock

    def __init__(self) -> None: ...

    def start(self) -> None: ...

    def update(self) -> None: ...
```

## Cocoa UI

`MacAgenticUI` is a native multi-tab interface opened with the global
Option-Space hotkey. The application starts with its window closed; the hotkey
opens or hides it without discarding tab state.

Each tab owns one independent `Agent`. Agent turns run asynchronously outside
AppKit's main thread, so multiple tabs may work concurrently while the UI
remains responsive. Requests submitted to a running tab are queued for that
tab.

Application setup creates the first `Agent`, then creates `MacAgenticUI` with
that agent. The UI assigns itself to `agent.ui` and places the agent in the
first tab. New tabs create additional agents directly using the global
configuration.

## Cocoa Layout

The window has a fixed 640-point content width. From top to bottom it contains:
- A fixed 48-point status bar with model usage and cost
- A fixed 24-point tab bar to select the active agent
- A variable-height conversation log
- A fixed 90-point input field.
The log grows with its content until the window reaches 90% of screen height, then scrolls.

## Cocoa Tabs

Each Cocoa tab owns:

```python
@dataclass
class UITab:
    # Identity and conversation
    id: int
    agent: Agent

    # Display state
    title: str = "New Agent"
    input_text: str = ""
    tool_call_descriptions: dict[str, str] = field(default_factory=dict)
    log_render_index: int = 0

    # Execution
    thread: threading.Thread | None = None
    requests: queue.Queue[str] = field(default_factory=queue.Queue)

    def running(self) -> bool: ...
```

Tab IDs increase monotonically and are never reused. Agent workers retain the
tab ID, Agent, and request queue; display workers retain only IDs and immutable
event data. Workers never retain the `UITab` object.

## UI Updates

```python
@dataclass(frozen=True)
class SetTabTitle:
    tab_id: int
    title: str


@dataclass(frozen=True)
class SetToolCallDescription:
    tab_id: int
    tool_call_id: str
    text: str


@dataclass(frozen=True)
class AgentThreadCompleted:
    tab_id: int
    thread_id: int


UIUpdate = SetTabTitle | SetToolCallDescription | AgentThreadCompleted
```

## Cocoa UI Class

`MacAgenticUI` is the top-level Cocoa application and owns all tabs, windows,
rendering, display state, and UI helper work:

```python
class MacAgenticUI:
    # Cocoa views and rendering
    window: NSWindow | None
    input_field: NSTextView | None
    text_view: NSTextView | None
    renderer: MarkdownRenderer
    bridge: MainThreadBridge  # Dispatches Cocoa work to AppKit's main thread.
    update_queue: queue.Queue[UIUpdate]

    # Tab state
    tabs: list[UITab]
    next_tab_id: int
    active_index: int
    focused_block: int

    def __init__(
        self,
        agent: Agent,
    ) -> None: ...

    @property
    def active_tab(self) -> UITab: ...

    def start(self, *, dont_run_app: bool = False) -> None: ...
    def update(self) -> None: ...
    def post_update(self, event: UIUpdate) -> None: ...

    def new_tab(self) -> None: ...
    def close_tab(self, index: int) -> None: ...
    def switch_tab(self, index: int) -> None: ...

    def submit(self, request: str) -> None: ...
    def interrupt_active(self, replacement: str = "") -> None: ...

    def close_window(self) -> None: ...
    def hotkey_pressed(self) -> None: ...
```

`update()` may be called from any thread. It asks the bridge to schedule a
main-thread update. UI workers call `post_update()` to append an immutable event
to `update_queue` before scheduling the same update.

On AppKit's main thread, the UI drains `update_queue`, discards events whose tab
or operation no longer exists, processes new conversation-log entries, applies
display-state changes, and renders. Only the main thread mutates tabs, so no tab
lock is needed.

Each running tab has one agent orchestration thread consuming its `requests`
queue. The worker posts a completion event instead of changing tab state
directly. Closing a tab removes it, interrupts its agent, and saves its complete
conversation log; later events for that tab are harmlessly discarded.

## Async Display Work

Tab titles and tool-call descriptions are UI-only model calls implemented
under `macagentic/ui/`. They use a shared asynchronous fast-model helper and
never block the agent thread or AppKit thread.

The UI detects tool-call events while processing new conversation-log entries
and starts asynchronous generation of their user-facing descriptions.

Title helpers post `SetTabTitle(tab_id, title)`. Missing tabs are ignored.

Description helpers post
`SetToolCallDescription(tab_id, tool_call_id, text)`. Results are stored by
tool call ID and rendered beside the corresponding call, regardless of the
order in which descriptions finish.