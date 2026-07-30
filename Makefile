.PHONY: run runui icon screenshot debug-render test test-ui test-tools \
	check-tools install-tools uninstall-tools tools-prompt

TOOLS_PROMPT := .build/tools.md

run: tools-prompt
	uv run --frozen python -m macagentic --tool-instructions "$(TOOLS_PROMPT)" $(ARGS)

runui: tools-prompt
	uv run --frozen python -m macagentic --ui --tool-instructions "$(TOOLS_PROMPT)" $(ARGS)

icon:
	uv run --frozen python scripts/render_app_icon.py

screenshot:
	uv run --frozen python -m macagentic.ui.screenshot_cli --output debug_screenshot.png

QUERY ?= What is 1+1?

debug-render: tools-prompt
	uv run --frozen python -m macagentic --ui --tool-instructions "$(TOOLS_PROMPT)" "$(QUERY)" --screenshot debug_screenshot.png

test:
	uv run --frozen python -m pytest

test-ui:
	uv run --frozen python -m pytest -m uitest

test-tools:
	uv run --frozen python -m pytest tools

check-tools:
	uv run --frozen python scripts/manage_tools.py check

install-tools:
	uv run --frozen python scripts/manage_tools.py install

uninstall-tools:
	uv run --frozen python scripts/manage_tools.py uninstall

tools-prompt:
	uv run --frozen python scripts/manage_tools.py prompt --output "$(TOOLS_PROMPT)"
