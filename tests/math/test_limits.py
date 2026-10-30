import time

import pytest

from yasno.math.limits import Deadline, MathTimeout, limited, time_limit


def _spin() -> int:
    while True:
        time.sleep(0.001)


def test_time_limit_interrupts_long_call() -> None:
    started = time.monotonic()
    with pytest.raises(MathTimeout), time_limit(0.05):
        _spin()
    assert time.monotonic() - started < 1


def test_limited_returns_default_on_timeout_and_error() -> None:
    assert limited(_spin, 0.05, -1) == -1
    assert limited(lambda: 1 // 0, 1, -2) == -2
    assert limited(lambda: 7, 1, 0) == 7


def _nested() -> None:
    limited(_spin, 5, 0)
    _spin()


def test_nested_limit_respects_outer_deadline() -> None:
    started = time.monotonic()
    with pytest.raises(MathTimeout), time_limit(0.05):
        _nested()
    assert time.monotonic() - started < 1


def test_deadline() -> None:
    assert not Deadline(10).expired()
    assert Deadline(0).expired()
