# Markdown Images

A Markdown image reference `![alt](source)` in the conversation log names a
local image file that the UI displays in place of the reference. How such
files are produced is outside this spec.

- Relative sources resolve against the agent root; absolute and `~` sources
  resolve normally. Remote sources are never fetched.
- The conversation log stores only the Markdown.
- An image that cannot be displayed falls back to its literal `![alt](source)`.

Both UIs obtain a display-ready PNG through one function:

```python
image_render.generate_render_image(
    source: str, *, base_directory: Path, max_pixels: tuple[int, int], card: bool
) -> Path  # raises ImageError
```

It resolves `source`, rejects URLs, scales down (never up) to `max_pixels`,
optionally draws a light card with a subdued border, and returns a PNG. Output
is content-addressed under `$TMPDIR/macagentic-images/` and reused.
