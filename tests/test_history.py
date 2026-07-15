from datetime import date

from macagentic.history import save_history


def test_history_uses_date_folder_and_next_number(tmp_path) -> None:
    today = date(2026, 7, 15)

    first = save_history(tmp_path, "First\n", today=today)
    second = save_history(tmp_path, "Second\n", today=today)

    assert first == tmp_path / "history.local/2026-07-15/session-1.md"
    assert second == tmp_path / "history.local/2026-07-15/session-2.md"
    assert first.read_text() == "First\n"
    assert second.read_text() == "Second\n"


def test_history_skips_empty_sessions(tmp_path) -> None:
    assert save_history(tmp_path, "") is None
    assert not (tmp_path / "history.local").exists()
