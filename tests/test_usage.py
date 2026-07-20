from macagentic.agent import UsageSnapshot, UsageTracker


def test_usage_tracker_accumulates_response_counters_and_cost() -> None:
    usage = UsageTracker()

    usage.add_response(
        {
            "usage": {
                "input_tokens": 1200,
                "input_tokens_details": {
                    "cached_tokens": 800,
                    "cache_write_tokens": 300,
                },
                "output_tokens": 100,
            },
            "extra": {"cost": 0.4},
        }
    )
    snapshot = usage.add_response(
        {
            "usage": {
                "input_tokens": 200,
                "input_tokens_details": {"cached_tokens": 100},
                "output_tokens": 50,
            },
            "extra": {"cost": 0.25},
        }
    )

    assert snapshot == UsageSnapshot(
        input_tokens=1400,
        cached_input_tokens=900,
        cache_write_tokens=300,
        output_tokens=150,
        cost=0.65,
    )
