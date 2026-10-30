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


class _State(threading.local):
    def __init__(self) -> None:
        self.deadlines: list[float] = []


_state = _State()


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


def expired() -> bool:
    return bool(_state.deadlines) and time.monotonic() >= _state.deadlines[-1]


def reraise_if_expired() -> None:
    if expired():
        raise MathTimeout


@contextmanager
def time_limit(seconds: float) -> Iterator[None]:
    now = time.monotonic()
    end = now + seconds
    if _state.deadlines:
        end = min(end, _state.deadlines[-1])
    if end <= now:
        raise MathTimeout
    alarm = _can_use_alarm()
    previous_handler = signal.signal(signal.SIGALRM, _raise_timeout) if alarm else None
    _state.deadlines.append(end)
    if alarm:
        signal.setitimer(signal.ITIMER_REAL, end - now)
    try:
        yield
    finally:
        _state.deadlines.pop()
        if alarm:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
            if _state.deadlines:
                signal.setitimer(
                    signal.ITIMER_REAL, max(_state.deadlines[-1] - time.monotonic(), 0.001)
                )


def limited[T](func: Callable[[], T], seconds: float, default: T) -> T:
    try:
        with time_limit(seconds):
            return func()
    except MathTimeout:
        if expired():
            raise
        return default
    except Exception:
        if expired():
            raise MathTimeout from None
        return default
