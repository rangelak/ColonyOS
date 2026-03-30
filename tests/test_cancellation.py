from __future__ import annotations

import signal
from unittest.mock import patch

from colonyos.cancellation import install_signal_cancel_handlers


class TestInstallSignalCancelHandlers:
    def test_handler_requests_shared_cancel_before_optional_hook(self) -> None:
        observed: list[tuple[int, str]] = []

        with patch("colonyos.cancellation.request_cancel") as mock_cancel, \
             patch("colonyos.cancellation.signal.getsignal", return_value=signal.SIG_DFL), \
             patch("colonyos.cancellation.signal.signal") as mock_signal:
            with install_signal_cancel_handlers(
                on_signal=lambda signum, sig_name: observed.append((signum, sig_name)),
                include_sighup=True,
            ):
                handlers = {
                    call.args[0]: call.args[1]
                    for call in mock_signal.call_args_list[:3]
                }
                handlers[signal.SIGINT](signal.SIGINT, object())

        mock_cancel.assert_called_once_with("SIGINT received")
        assert observed == [(signal.SIGINT, "SIGINT")]

    def test_sigterm_preserves_exit_code_semantics(self) -> None:
        with patch("colonyos.cancellation.request_cancel") as mock_cancel, \
             patch("colonyos.cancellation.signal.getsignal", return_value=signal.SIG_DFL), \
             patch("colonyos.cancellation.signal.signal") as mock_signal:
            with install_signal_cancel_handlers():
                handler = mock_signal.call_args_list[1].args[1]
                try:
                    handler(signal.SIGTERM, object())
                    raise AssertionError("SIGTERM handler should exit")
                except SystemExit as exc:
                    assert exc.code == 128 + signal.SIGTERM

        mock_cancel.assert_called_once_with("SIGTERM received")
