from macagentic.agent import ConversationLog
from macagentic.app import app
from macagentic.session import load_session
from macagentic.ui.cli import CommandLineUI


def run_ui(*, initial_task: str | None = None) -> None:
    from Cocoa import NSApplication

    from macagentic.ui.core import MacAgenticUI, UITab

    saved = load_session(app.workspace)
    if saved is None:
        ui = MacAgenticUI(app.create_agent(render_markdown=True))
    else:
        tabs = []
        for saved_tab in saved.tabs:
            agent = app.create_agent(
                render_markdown=True,
                agent_id=saved_tab.id,
                messages=saved_tab.messages,
                conversation_log=ConversationLog(saved_tab.events),
            )
            tabs.append(
                UITab(
                    id=agent.id,
                    agent=agent,
                    title=saved_tab.title,
                    input_text=saved_tab.input_text,
                )
            )
        ui = MacAgenticUI(
            tabs[0].agent,
            tabs=tabs,
            active_index=saved.active_index,
        )
    ui.start(dont_run_app=True)
    if app.screenshot_path is not None:
        ui.hotkey_pressed(activate=False)
    if initial_task:
        ui.submit(initial_task)
    NSApplication.sharedApplication().run()

__all__ = ["CommandLineUI", "run_ui"]
