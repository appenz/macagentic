# macOS UI

## Core Principle

**The UI is a passive renderer for the agent.**

The agent must run identically with or without the UI. It writes user and
assistant text to a plain Markdown stream. When `--ui` is active, the UI reads
that stream and renders it. Without `--ui`, the same agent uses terminal input
and output.

The agent must never import, own, inspect, or otherwise depend on UI code.

There are only two permitted exceptions:

1. After changing transcript or usage state, the agent may trigger an optional
   repaint callback.
2. When blocked, the agent may ask the UI for permission or clarification.

If no UI is attached, repaint is a no-op and permission or clarification uses
the terminal.

## Architecture

Each UI tab owns an in-memory, file-like Markdown stream.

The stream contains user and assistant display text plus short, marked tool
status events in order. It never contains model payloads, reasoning metadata,
or debug records. Raw tool output appears only with `--tooloutput`.

The UI renders the stream as one Markdown document. It does not reconstruct
messages, query the agent, or maintain a second conversation representation.

Model usage is maintained separately from the stream. The UI may render a
read-only usage snapshot, but usage metadata never enters the transcript.

The Cocoa event loop stays on the main thread. Agent work runs outside the main
thread. Repaint requests from agent threads are dispatched asynchronously to
the main thread.

## Sessions

Each tab owns an independent agent conversation, transcript stream, and input
draft. Closing a non-empty tab saves a debug-style Markdown history under
`history.local/YYYY-MM-DD/`; application termination is not a persistence
boundary. Agent work may continue in background tabs, and input submitted to a
running tab is queued for that tab.

Permission and clarification are exposed through two purpose-specific optional
callbacks, keeping the agent-to-UI interface limited to blocking requests.

## Interrupts

Interrupts are cooperative. Each running tab has a cancel flag owned by the
agent control layer.

Cancellation is checked while waiting for input and before and after model
calls and tool execution. Subprocess process groups should be terminated where
possible. Python worker threads must never be killed asynchronously.

An in-flight model call may not be cancellable. In that case its eventual
result is discarded and never written to the transcript. A run identifier
prevents output from an interrupted run from appearing after a newer run.

The UI invokes the same interrupt operation as terminal Control-C. The UI does
not add synthetic transcript text. If `Interrupted.` should appear, the control
layer writes it through the normal transcript path.

## Testing Boundary

UI testing may drive the Cocoa event loop and capture rendered windows, but
test instrumentation remains outside the agent and transcript abstractions.
