import signal
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType

MAX_INPUT_LENGTH = 400
MAX_NODES = 300
MAX_DEGREE = 12
MAX_EXPONENT_BITS = 4000
MAX_INTEGER_DIGITS = 15


class MathTimeout(BaseException):
    pass


class Deadline:
    def __init__(self, seconds: float) -> None:
        self._end = time.monotonic() + seconds

    def remaining(self) -> float:
        return self._end - time.monotonic()

    def expired(self) -> bool:
        return self.remaining() <= 0


def _can_use_alarm() -> bool:
    return hasattr(signal, "setitimer") and threading.current_thread() is threading.main_thread()


def _raise_timeout(signum: int, frame: FrameType | None) -> None:
    raise MathTimeout


@contextmanager
def time_limit(seconds: float) -> Iterator[None]:
    if seconds <= 0:
        raise MathTimeout
    if not _can_use_alarm():
        yield
        return
    previous_delay, _ = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    if 0 < previous_delay < seconds:
        seconds = previous_delay
    previous_handler = signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_delay > 0:
            left = previous_delay - (time.monotonic() - started)
            signal.setitimer(signal.ITIMER_REAL, max(left, 0.001))


def limited[T](func: Callable[[], T], seconds: float, default: T) -> T:
    try:
        with time_limit(seconds):
            return func()
    except (MathTimeout, Exception):
        return default
