from macagentic.app import app
from macagentic.ui.cli import CommandLineUI


def run_ui(*, initial_task: str | None = None) -> None:
    from Cocoa import NSApplication

    from macagentic.ui.core import MacAgenticUI

    ui = MacAgenticUI(app.create_agent(render_markdown=True))
    ui.start(dont_run_app=True)
    if app.screenshot_path is not None:
        ui.hotkey_pressed()
    if initial_task:
        ui.submit(initial_task)
    NSApplication.sharedApplication().run()

__all__ = ["CommandLineUI", "run_ui"]
