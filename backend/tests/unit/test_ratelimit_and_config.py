import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services import ratelimit
from app.services.ratelimit import SlidingWindow


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(ratelimit.time, "monotonic", c)
    return c


def test_allows_up_to_the_limit_then_refuses(clock):
    w = SlidingWindow()
    assert [w.allow("a", 3, 60) for _ in range(5)] == [True, True, True, False, False]


def test_the_window_slides(clock):
    w = SlidingWindow()
    for _ in range(2):
        assert w.allow("a", 2, 60)
    assert not w.allow("a", 2, 60)
    clock.now += 30
    assert not w.allow("a", 2, 60)  # the first two events are still inside the window
    clock.now += 31
    assert w.allow("a", 2, 60)  # ...and now they have aged out


def test_keys_are_independent(clock):
    w = SlidingWindow()
    assert w.allow("a", 1, 60) and not w.allow("a", 1, 60)
    assert w.allow("b", 1, 60)


@pytest.mark.parametrize("limit", [0, -1])
def test_a_non_positive_limit_means_unlimited(clock, limit):
    w = SlidingWindow()
    assert all(w.allow("a", limit, 60) for _ in range(1000))


def test_retry_after_counts_down(clock):
    w = SlidingWindow()
    w.allow("a", 1, 60)
    assert 59 <= w.retry_after("a", 60) <= 61
    clock.now += 50
    assert w.retry_after("a", 60) <= 11
    assert w.retry_after("never-seen", 60) == 1


def test_memory_is_bounded(clock):
    w = SlidingWindow()
    for i in range(10_500):
        w.allow(i, 1, 1)
        clock.now += 0.01
    clock.now += 5
    w.allow("trigger", 1, 1)
    assert len(w._events) < 10_001


GOOD = "postgresql+psycopg://chess:s3cure-random-pw@db:5432/chess"
PLACEHOLDER = "postgresql+psycopg://chess:change-me@db:5432/chess"


def test_production_refuses_the_placeholder_database_password():
    with pytest.raises(ValidationError, match="placeholder password"):
        Settings(environment="production", database_url=PLACEHOLDER)
    with pytest.raises(ValidationError):
        Settings(environment="Production", database_url=PLACEHOLDER)  # case does not matter


def test_production_accepts_a_real_password():
    assert Settings(environment="production", database_url=GOOD).environment == "production"


def test_development_may_use_the_placeholder():
    assert Settings(environment="development", database_url=PLACEHOLDER).environment == "development"
    assert Settings(database_url=PLACEHOLDER)  # default environment
