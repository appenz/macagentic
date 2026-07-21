# Configuration

`config/config.toml` provides project defaults.
`~/.config/macagentic/config.toml` overrides those defaults.

Supported keys are `model`, `openai_api_key`, `brave_api_key`, and
`custom_prompt`. A `[mounts]` table maps short relative paths to existing user
directories. Parent directories are created automatically, and each mount is
exposed as a symlink in every agent root.
Command-line options override TOML values.

The global runtime configuration also contains `show_tool_output`. It is set
from the command line and is not a TOML key.
