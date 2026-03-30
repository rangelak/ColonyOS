from __future__ import annotations

import logging
import signal
import threading
import uuid
from contextlib import contextmanager
from typing import Callable, Iterator

logger = logging.getLogger(__name__)

CancelCallback = Callable[[str], None]

_CALLBACKS_LOCK = threading.Lock()
_CANCEL_CALLBACKS: dict[str, CancelCallback] = {}


def register_cancel_callback(callback: CancelCallback) -> str:
    """Register a callback to run when global cancellation is requested."""
    token = uuid.uuid4().hex
    with _CALLBACKS_LOCK:
        _CANCEL_CALLBACKS[token] = callback
    return token


def unregister_cancel_callback(token: str) -> None:
    """Remove a previously registered cancellation callback."""
    with _CALLBACKS_LOCK:
        _CANCEL_CALLBACKS.pop(token, None)


@contextmanager
def cancellation_scope(callback: CancelCallback) -> Iterator[str]:
    """Register a cancellation callback for the duration of a scope."""
    token = register_cancel_callback(callback)
    try:
        yield token
    finally:
        unregister_cancel_callback(token)


def request_cancel(reason: str = "Cancelled by user") -> int:
    """Invoke all registered cancellation callbacks.

    Returns the number of callbacks that were signaled.
    """
    with _CALLBACKS_LOCK:
        callbacks = list(_CANCEL_CALLBACKS.items())
    for token, callback in callbacks:
        try:
            callback(reason)
        except Exception:
            logger.exception("Cancellation callback %s failed", token)
    return len(callbacks)


@contextmanager
def install_signal_cancel_handlers(
    *,
    on_signal: Callable[[int, str], None] | None = None,
    include_sighup: bool = False,
) -> Iterator[None]:
    """Temporarily install signal handlers that fan into shared cancellation."""
    signals_to_manage = [signal.SIGINT, signal.SIGTERM]
    if include_sighup and hasattr(signal, "SIGHUP"):
        signals_to_manage.append(signal.SIGHUP)

    previous_handlers = {
        managed_signal: signal.getsignal(managed_signal)
        for managed_signal in signals_to_manage
    }

    def _handler(signum: int, frame: object) -> None:
        sig_name = signal.Signals(signum).name
        request_cancel(f"{sig_name} received")
        if on_signal is not None:
            on_signal(signum, sig_name)
            return
        if signum == signal.SIGINT:
            raise KeyboardInterrupt(f"{sig_name} received")
        raise SystemExit(128 + signum)

    for managed_signal in signals_to_manage:
        signal.signal(managed_signal, _handler)
    try:
        yield
    finally:
        for managed_signal, previous_handler in previous_handlers.items():
            signal.signal(managed_signal, previous_handler)
