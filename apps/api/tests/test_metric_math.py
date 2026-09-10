"""Percentile helper used by the metrics rollup.

SQLite has no percentile function, so the maths lives in Python and is worth
pinning down on its own.
"""

from hymail_api.services.metrics import percentile


def test_percentile_of_nothing_is_none() -> None:
    assert percentile([], 0.95) is None


def test_percentile_picks_the_nearest_rank() -> None:
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

    assert percentile(values, 0.5) == 50
    assert percentile(values, 0.95) == 100
    assert percentile(values, 0.0) == 10


def test_percentile_does_not_depend_on_input_order() -> None:
    assert percentile([100, 10, 50], 0.5) == percentile([10, 50, 100], 0.5)


def test_percentile_of_a_single_value_is_that_value() -> None:
    assert percentile([7], 0.95) == 7
