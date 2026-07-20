import os
import signal
import sys
import threading

from macagentic.agent import Agent
from macagentic.app import app
from macagentic.ui.projection import format_usage, render_conversation


class CommandLineUI:
    agent: Agent
    log_render_index: int
    show_tool_output: bool
    update_lock: threading.Lock

    def __init__(self) -> None:
        self.agent = app.create_agent()
        self.agent.ui = self
        self.log_render_index = 0
        self.show_tool_output = app.show_tool_output
        self.update_lock = threading.Lock()

    def start(self) -> None:
        previous_handler = signal.getsignal(signal.SIGINT)

        def handle_sigint(_signum, _frame) -> None:
            self.agent.interrupt()

        signal.signal(signal.SIGINT, handle_sigint)
        try:
            while True:
                try:
                    request = input("\nYou: ").strip()
                except KeyboardInterrupt:
                    self.agent.interrupt()
                    print("\nInterrupted.")
                    continue
                except EOFError:
                    print()
                    return

                if request.lower() in {"/exit", "/quit"}:
                    return
                if not request:
                    continue

                self.agent.run_turn(request)
                snapshot = self.agent.usage.snapshot()
                color = bool(
                    getattr(sys.stdout, "isatty", lambda: False)()
                    and "NO_COLOR" not in os.environ
                )
                print(format_usage(snapshot, color=color), flush=True)
        finally:
            signal.signal(signal.SIGINT, previous_handler)

    def update(self) -> None:
        with self.update_lock:
            events = self.agent.conversation_log.snapshot()
            new_events = events[self.log_render_index :]
            self.log_render_index = len(events)
            content = render_conversation(
                new_events,
                show_tool_output=self.show_tool_output,
            )
            if content:
                print(content, end="", flush=True)


def run_batch(request: str) -> None:
    agent = app.create_agent()
    agent.run_turn(request)
    content = render_conversation(
        agent.conversation_log.snapshot(),
        show_tool_output=app.show_tool_output,
    )
    if content:
        print(content, end="")
    print(format_usage(agent.usage.snapshot()))
