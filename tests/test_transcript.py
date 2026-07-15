from macagentic.agent.transcript import Transcript


def test_transcript_keeps_text_in_memory_and_notifies() -> None:
    notifications = []
    transcript = Transcript(on_change=lambda: notifications.append(True))

    transcript.write("first")
    transcript.write(" second")
    assert transcript.replace_last("second", "updated")

    assert transcript.getvalue() == "first updated"
    assert not transcript.replace_last("missing", "")
    assert len(notifications) == 3
