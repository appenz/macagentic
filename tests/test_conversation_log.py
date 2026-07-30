from macagentic.agent import ConversationLog


def test_conversation_log_preserves_order_and_copies_payloads() -> None:
    log = ConversationLog()
    message = {"role": "user", "content": "hello"}

    log.append("user_input", {"content": "hello"})
    log.append_message(message)
    message["content"] = "changed"

    events = log.snapshot()
    assert [event.kind for event in events] == [
        "user_input",
        "message",
    ]
    assert events[1].payload == {
        "role": "user",
        "content": "hello",
    }


def test_conversation_log_snapshots_do_not_mutate_ledger() -> None:
    log = ConversationLog()
    log.append_message({"role": "user", "content": "hello"})

    snapshot = log.snapshot()
    snapshot[0].payload["content"] = "changed"

    assert log.snapshot()[0].payload["content"] == "hello"


def test_conversation_log_records_round_trip() -> None:
    records = [
        {"kind": "user_input", "payload": {"content": "hello"}},
        {
            "kind": "message",
            "payload": {"role": "user", "content": "hello"},
        },
    ]

    assert ConversationLog(records).records() == records
