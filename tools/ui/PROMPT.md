### `ui` command for macOS automation.
- Screenshot full screen: `ui screenshot`
- Click at coordinates: `ui click X Y` (e.g., `ui click 500 100`)
- Type text: `ui type "text to type"`

**Use cases:**
- When the task requires interacting with a GUI application (Safari, Finder, etc.)
- When you need to see what's on screen — screenshot output is wrapped in `<MSWEA_MULTIMODAL_CONTENT>` tags so vision models receive it as an image automatically
- When clicking buttons, menus, or UI elements is needed

**How to use for Safari navigation:**
1. First open Safari with bash: `open -a Safari`
2. Click the address bar at coordinates (find it by screenshot first)
3. Type "yahoo.com" using `ui type "yahoo.com"`
4. Press Enter key (use `ui type "\n"` or click Return button)
5. Take a screenshot to verify

**Note:** The agent must first open Safari using bash (`open -a Safari`) before using UI tools to interact with it.
