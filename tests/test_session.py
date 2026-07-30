from pathlib import Path

from macagentic.session import (
    SavedSession,
    SavedTab,
    load_session,
    save_session,
)


def test_session_round_trip_and_workspace_match(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = tmp_path / "open-tabs.json"
    session = SavedSession(
        workspace=str(workspace.resolve()),
        active_index=0,
        tabs=[
            SavedTab(
                id=3,
                title="Persist tabs",
                input_text="draft",
                messages=[{"role": "user", "content": "hello"}],
                events=[
                    {
                        "kind": "user_input",
                        "payload": {"content": "hello"},
                    }
                ],
            )
        ],
    )

    save_session(session, path=path)

    assert load_session(workspace, path=path) == session
    assert not path.with_suffix(".tmp").exists()
    assert load_session(tmp_path, path=path) is None


def test_missing_session_returns_none(tmp_path: Path) -> None:
    assert load_session(tmp_path, path=tmp_path / "missing.json") is None
