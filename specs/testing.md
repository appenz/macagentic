# Testing

## Screenshot tests

- Prompt → UI → PNG: `uv run python -m macagentic --ui --task "…" --screenshot PATH` (real agent turn, then quit).
- Markdown → UI → PNG: `uv run python -m scripts.manual_math_render --case NAME` (canned math fixtures under `/tmp/macagentic-math-debug/`).
- Capture helpers: `macagentic/ui/screenshot.py`, `UITestDriver.screenshot()`, `screenshot_cli.py`.
