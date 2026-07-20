import os
import signal
import subprocess
import threading
from typing import Any

from minisweagent.environments.local import LocalEnvironment


class ShellEnvironment(LocalEnvironment):
    """Local shell environment with cooperative process interruption."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._processes: set[subprocess.Popen] = set()
        self._processes_lock = threading.Lock()

    def execute(
        self,
        action: dict,
        cwd: str = "",
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        command = action.get("command", "")
        cwd = cwd or self.config.cwd or os.getcwd()
        try:
            result = self._run(
                command,
                cwd,
                os.environ | self.config.env,
                timeout or self.config.timeout,
            )
            output = {
                "output": result.stdout,
                "returncode": result.returncode,
                "exception_info": "",
            }
        except Exception as error:
            raw_output = getattr(error, "output", None)
            if isinstance(raw_output, bytes):
                raw_output = raw_output.decode("utf-8", errors="replace")
            output = {
                "output": raw_output or "",
                "returncode": -1,
                "exception_info": (
                    f"An error occurred while executing the command: {error}"
                ),
                "extra": {
                    "exception_type": type(error).__name__,
                    "exception": str(error),
                },
            }
        self._check_finished(output)
        return output

    def interrupt(self) -> None:
        with self._processes_lock:
            processes = tuple(self._processes)
        for process in processes:
            _terminate(process)

    def _run(
        self,
        command: str,
        cwd: str,
        env: dict[str, str],
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        process = subprocess.Popen(
            command,
            shell=True,
            text=True,
            cwd=cwd,
            env=env,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=os.name == "posix",
        )
        with self._processes_lock:
            self._processes.add(process)
        try:
            try:
                stdout, _ = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _terminate(process)
                stdout, _ = process.communicate()
                raise subprocess.TimeoutExpired(
                    command,
                    timeout,
                    output=stdout,
                )
            except BaseException:
                _terminate(process)
                process.communicate()
                raise
            return subprocess.CompletedProcess(
                command,
                process.returncode,
                stdout=stdout,
            )
        finally:
            with self._processes_lock:
                self._processes.discard(process)


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        os.killpg(process.pid, signal.SIGKILL)
    else:
        process.kill()
