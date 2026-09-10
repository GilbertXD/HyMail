from hymail_api.sync.backoff import calculate_backoff_delay


def test_backoff_delay_grows_exponentially() -> None:
    assert calculate_backoff_delay(1, base_seconds=1.0) == 1.0
    assert calculate_backoff_delay(2, base_seconds=1.0) == 2.0
    assert calculate_backoff_delay(3, base_seconds=1.0) == 4.0


def test_backoff_delay_is_capped() -> None:
    assert calculate_backoff_delay(
        10,
        base_seconds=1.0,
        max_seconds=5.0,
    ) == 5.0


def test_backoff_delay_for_zero_attempts() -> None:
    assert calculate_backoff_delay(0) == 0.0