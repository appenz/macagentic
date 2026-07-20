# macAgentic Overview

**IMPORTANT:** Before writing any code or making architecture decisions, read:

1. This Overview spec
2. Any specs relevant to the task in the `specs/` folder.
3. If you are writing tests, any relevant spec in the `tests/specs` folder

macAgentic is a macOS-native agent written in Python.

# Agent

The `Agent` object owns a conversation with the user.
- It contains the core agentic loop
- `Agent.messages` contains the sequence of inputs, tool calls, tool outputs and the replies to the user
- `Agent.conversation_log` is an ordered, append-only ledger containing `messages` plus UI relevant data
  - Every `messages` entry is copied into `conversation_log` in order, with additional events interleaved.
  - Additionally data represents data absent from messages (e.g. unexpanded user input)
- `Agent` owns no UI state and imports no UI implementations
- `Agent.ui` is an optional (may be None) reference to the current UI for the special cases listed below

# User Interface

There are two user interfaces, cli and a Cocoa UI.
- All UI specific functionality is implemented in `ui/`, none in agent.
- The UI may freely read `Agent` state that it needs to provide updates to the user:
  - It renders the `conversation_log`
  - It may read other state, e.g. usage and cost
- The `Agent` may not read UI state
- Method calls between `Agent` and UI are strictly limited to the following calls ONLY:
  - agent.ui.update() - Refresh the UI
  - ui → agent.run_turn(request) - Ask the agent to run this request
  - ui → agent.interrupt() - Ask the agent to stop