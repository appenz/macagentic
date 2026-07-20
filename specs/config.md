# Configuration

`config/config.toml` provides project defaults.
`~/.config/macagentic/config.toml` overrides those defaults.

Supported keys are `model`, `openai_api_key`, `brave_api_key`, and
`custom_prompt`.
Command-line options override TOML values.

The global runtime configuration also contains `show_tool_output`. It is set
from the command line and is not a TOML key.
