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
output projection, usage display, `/exit`, and signal handling. Model-tier
slash commands (`/fast`, `/medium`, `/slow`) are handled inside `Agent.run_turn`
and surface as `model_switch` conversation-log events. It creates the agent with
`ui=self`; `update()` reads and prints new conversation-log entries.

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
configuration. Model selection is per tab via the Model menu (Cmd-1/2/3) or
slash commands; menu and Cmd-1/2/3 call `agent.set_model_tier` on the active
tab without appending a `model_switch` message.

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
class UITab:
    # Identity and agent
    id: int  # The Agent's process-local ID.
    agent: Agent

    # Persisted state (see session restore)
    title: str
    input_text: str  # Synchronized from input_text_view for persistence.

    # Display state
    tool_call_descriptions: dict[str, str]  # Keyed by tool call ID.
    display_event_index: int  # Next conversation-log entry to render.
    math_bitmap_cache: MathBitmapCache
    expanded_block_ids: set[str]

    # Persistent Cocoa views, created lazily on first mount
    tab_bar_item: TabBarItemView | None
    content_view: TabContentView | None

    # Execution state
    thread: threading.Thread | None  # Agent orchestration thread, if running.
    requests: queue.Queue[str]  # Queued requests consumed by `thread`.

    def __init__(self, tab_id: int, agent: Agent, *, title: str, input_text: str) -> None: ...

    def running(self) -> bool: ...
```

`UITab` is a regular mutable class, not a dataclass. It is a long-lived UI
object with persistent Cocoa view identity and changing execution and display
state. Each tab uses its Agent's process-local ID.

`TabBarItemView` owns the persistent Cocoa controls for one tab-bar item:

```python
class TabBarItemView(NSView):
    tab_id: int
    title_label: NSTextField
    close_button: NSView
    active_background: NSBox

    def set_title(self, title: str, *, running: bool) -> None: ...
    def set_active(self, active: bool) -> None: ...
```

`TabContentView` owns all Cocoa controls and interaction metadata for one tab's
status, transcript, and input areas:

```python
class TabContentView(NSView):
    status_view: NSTextView
    transcript_scroll: NSScrollView
    transcript_view: ConversationTextView
    input_scroll: NSScrollView
    input_text_view: NSTextView
    input_delegate: InputDelegate
    conversation_delegate: ConversationDelegate
    markdown_display_map: MarkdownDisplayMap | None
    focused_block: int

    def set_status(self, agent: Agent) -> None: ...
    def set_transcript(
        self,
        cocoa_text: NSMutableAttributedString,
        markdown_display_map: MarkdownDisplayMap,
    ) -> None: ...
    def input_text(self) -> str: ...
    def clear_input(self) -> None: ...
```

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

`MacAgenticUI` is the top-level Cocoa application. It owns the persistent
window shell, shared renderer, tab collection, update routing, and UI helper
work. Per-tab Cocoa controls and interaction state belong to each `UITab`:

```python
class MacAgenticUI:
    # Persistent window shell
    window: NSWindow | None
    root_view: NSBox | None
    tab_bar_container: NSView | None
    tab_content_container: NSView | None

    # Shared rendering service and update bridge
    renderer: MarkdownRenderer
    bridge: MainThreadBridge  # Dispatches Cocoa work to AppKit's main thread.
    update_queue: queue.Queue[UIUpdate]

    # Tab state
    tabs: list[UITab]
    active_index: int

    def __init__(
        self,
        agent: Agent,
    ) -> None: ...

    @property
    def active_tab(self) -> UITab: ...

    @property
    def active_content_view(self) -> TabContentView | None: ...

    def start(self, *, dont_run_app: bool = False) -> None: ...
    def update(self) -> None: ...
    def post_update(self, event: UIUpdate) -> None: ...

    def new_tab(self) -> None: ...
    def close_tab(self, index: int) -> None: ...
    def switch_tab(self, index: int) -> None: ...
    def cycle_tab(self, delta: int = 1) -> None: ...

    def submit(self, request: str) -> None: ...
    def interrupt_active(self, replacement: str = "") -> None: ...
    def set_active_model_tier(self, tier: str) -> None: ...

    def close_window(self) -> None: ...
    def hotkey_pressed(self) -> None: ...
```

Ctrl-Tab / Ctrl-Shift-Tab cycle the active tab forward or backward (wrapping).

The Model menu lists Fast / Medium / Slow with configured model names and
template icons from `macagentic/ui/assets/model_*.png`.

The window shell, tab-bar container, and tab-content container are created once.
Each tab's `TabContentView` and `TabBarItemView` are created lazily and retained
by that tab. Switching tabs hides the outgoing content view and shows the
incoming view; it does not detach or recreate either tab's controls. Closing
the application window orders the persistent window out and reopening orders
the same window and controls back in.


`update()` may be called from the main thread or a tab's orchestration thread.
Main-thread calls belong to the active tab. Worker-thread calls are matched to
the `UITab` whose `thread` is the caller, and the tab ID is passed through the
bridge to the main thread. Calls from unmatched threads are ignored. In
particular, usage accounting does not request an update from the nested model
query thread; the subsequent response append on the tab thread renders both the
response and its already-recorded usage.

Updates attributed to the active tab process its new conversation-log entries
and update that tab's existing Cocoa controls. Updates attributed to an
inactive tab do not process its deferred display work or mutate any content
view. When the user switches tabs, the newly active tab processes its deferred
entries before its persistent content view is shown.

UI helpers call `post_update()` to append an immutable event to `update_queue`
and schedule an event-only main-thread pass. `SetToolCallDescription` is stored
for every existing tab but triggers a full render only for the active tab.
`SetTabTitle` and `AgentThreadCompleted` update the matching visible title label
through `UITab.tab_bar_item` in place, including its running indicator, without
rebuilding the window or content views.

On AppKit's main thread, the UI drains `update_queue`, discards events whose tab
or operation no longer exists, and applies the scoped behavior above. Only the
main thread mutates tabs, so no tab lock is needed.

Each running tab has one agent orchestration thread consuming its `requests`
queue. The worker posts a completion event instead of changing tab state
directly. Closing a tab removes it, interrupts its agent, and saves its complete
conversation log; later events for that tab are harmlessly discarded.

Every tab owns its own persistent `input_text_view`. Switching tabs therefore
changes which complete `TabContentView` is visible; input text, selection, undo
state, and first-responder identity do not migrate between tabs. `UITab.input_text`
is synchronized from that view for session persistence and initializes the
view when a restored tab is first mounted.

The shared `MarkdownRenderer` retains only its parser/configuration. A render
returns the Cocoa attributed string plus a document-specific
`MarkdownDisplayMap`. The map belongs to the tab content view and contains no
Cocoa objects:

```python
@dataclass(frozen=True)
class MarkdownDisplayMap:
    markdown_source: str
    source_spans: tuple[tuple[int, int, int, int], ...]
    block_contents: Mapping[str, str]
    block_ranges: tuple[tuple[str, int, int], ...]

    def markdown_for_range(self, char_range: tuple[int, int]) -> str: ...
    def block_content(self, block_id: str) -> str | None: ...


class MarkdownRenderer:
    def render(
        self,
        markdown: str,
        color: NSColor,
        *,
        expanded_block_ids: set[str],
        math_bitmap_cache: MathBitmapCache,
        scale_factor: float,
    ) -> tuple[NSMutableAttributedString, MarkdownDisplayMap]: ...
```

Copy, collapsible-block links, and keyboard block focus resolve against the
active `TabContentView.markdown_display_map`; the shared renderer has no
selection, block-focus, expansion, or last-document state.

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

Normal termination persists open tabs and conversations; startup restores them
when `app.workspace` matches, while runtime and display caches start fresh.

## Files

- `macagentic/ui/__init__.py`: Cocoa UI entry point (`run_ui`).
- `macagentic/ui/cli.py`: `CommandLineUI` and batch CLI runner.
- `macagentic/ui/core.py`: `MacAgenticUI`, Cocoa window, tabs, and rendering orchestration.
- `macagentic/ui/markdown.py`: Native Cocoa Markdown renderer.
- `macagentic/ui/math_render.py`: LaTeX math bitmap rendering (see `specs/math_rendering.md`).
- `macagentic/ui/projection.py`: Terminal conversation-log projection and usage formatting.
- `macagentic/ui/updates.py`: Immutable UI update events.
- `macagentic/ui/helpers/fast_llm.py`: Asynchronous fast-model helper for titles and descriptions.
- `macagentic/ui/helpers/assistant_text.py`: Extract assistant text from model responses.
- `macagentic/ui/screenshot.py`: Quartz window screenshot capture.
- `macagentic/ui/screenshot_cli.py`: CLI entry point for screenshot capture.
- `macagentic/ui/testing.py`: In-process Cocoa UI test driver.

Screenshot testing is available; see `specs/testing.md`.