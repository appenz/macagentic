# CLI Rendering

The CLI prints the conversation log as plain text. Markdown is passed through
verbatim, not parsed. `macagentic/ui/conversation_markdown.py` turns log
events into Markdown (the Cocoa UI uses the same module as its renderer
input); `macagentic/ui/cli.py` prints it. The Cocoa rendering of the same log is
specified in `specs/markdown_cocoa.md`.

## Projection

- `user_input` → `**You:** <content>`
- `message` → assistant text as written; status fences omitted
- `tool_execution` → command, exit code, and output in a `text` fence, only
  with `show_tool_output`
- `interrupted` → `Interrupted.`
- `model_switch` → `Switching to <model>`

Usage follows each turn via `format_usage()`, colored when stdout is a TTY and
`NO_COLOR` is unset.

## Images

```python
terminal_images.inline_images(markdown: str, base_directory: Path) -> str
```

When stdout is a TTY and `KITTY_WINDOW_ID` is set or `TERM_PROGRAM` is
`ghostty`, each line that is only an image reference is replaced by the
`generate_render_image()` PNG (`specs/markdown_images.md`, sized to the
terminal, no card) via the Kitty graphics protocol. Otherwise the input is
returned unchanged.

## Files

- `macagentic/ui/conversation_markdown.py`: log-to-Markdown and usage formatting.
- `macagentic/ui/terminal_images.py`: `inline_images()`.
- `macagentic/ui/cli.py`: `CommandLineUI` and batch runner.
