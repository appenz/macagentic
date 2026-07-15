from collections.abc import Callable
from io import StringIO
from threading import RLock


class Transcript:
    """A thread-safe, in-memory Markdown stream for passive renderers."""

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self._buffer = StringIO()
        self._lock = RLock()
        self._on_change = on_change

    def set_on_change(self, callback: Callable[[], None] | None) -> None:
        with self._lock:
            self._on_change = callback

    def write(self, text: str) -> None:
        with self._lock:
            self._buffer.write(text)
            callback = self._on_change
        if callback is not None:
            callback()

    def replace_last(self, old: str, new: str) -> bool:
        with self._lock:
            value = self._buffer.getvalue()
            index = value.rfind(old)
            if index < 0:
                return False
            self._buffer = StringIO(
                value[:index] + new + value[index + len(old) :]
            )
            self._buffer.seek(0, 2)
            callback = self._on_change
        if callback is not None:
            callback()
        return True

    def getvalue(self) -> str:
        with self._lock:
            return self._buffer.getvalue()
