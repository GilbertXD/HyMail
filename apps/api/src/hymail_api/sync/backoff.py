def calculate_backoff_delay(
    attempts: int,
    *,
    base_seconds: float = 1.0,
    max_seconds: float = 300.0,
) -> float:
    if attempts < 1:
        return 0.0
    return min(base_seconds * (2 ** (attempts - 1)), max_seconds)