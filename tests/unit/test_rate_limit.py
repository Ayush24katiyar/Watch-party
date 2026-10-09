from watch_party.domain.rate_limit import TokenBucket


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_allows_burst_up_to_capacity() -> None:
    clock = FakeClock()
    bucket = TokenBucket(rate_per_second=5, capacity=5, clock=clock)

    assert all(bucket.consume() for _ in range(5))
    assert not bucket.consume()


def test_refills_over_time() -> None:
    clock = FakeClock()
    bucket = TokenBucket(rate_per_second=5, capacity=5, clock=clock)
    for _ in range(5):
        assert bucket.consume()

    clock.advance(0.4)  # 0.4s * 5/s = 2 tokens
    assert bucket.consume()
    assert bucket.consume()
    assert not bucket.consume()


def test_tokens_never_exceed_capacity() -> None:
    clock = FakeClock()
    bucket = TokenBucket(rate_per_second=5, capacity=3, clock=clock)

    clock.advance(100)
    assert bucket.consume(3)
    assert not bucket.consume(1)


def test_rejects_non_positive_rate() -> None:
    import pytest

    with pytest.raises(ValueError):
        TokenBucket(rate_per_second=0)
