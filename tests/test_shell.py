import threading
import time

from macagentic.agent import ShellEnvironment


def test_interrupt_terminates_running_command() -> None:
    shell = ShellEnvironment(timeout=30)
    results = []
    execution = threading.Thread(
        target=lambda: results.append(
            shell.execute({"command": "sleep 30"})
        )
    )
    execution.start()

    deadline = time.monotonic() + 1
    while not shell._processes and time.monotonic() < deadline:
        time.sleep(0.01)

    shell.interrupt()
    execution.join(1)

    assert not execution.is_alive()
    assert results[0]["returncode"] != 0
