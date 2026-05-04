"""Unit tests for snitchbot.integrations.celery.install."""
from unittest.mock import MagicMock, patch

import pytest


class _FakeSignal:
    """Minimal celery.signals.worker_process_init double."""

    def __init__(self) -> None:
        self.receivers: list = []

    def connect(self, *, weak: bool = True):
        def _decorator(fn):
            self.receivers.append((fn, weak))
            return fn
        return _decorator


@pytest.fixture
def fake_celery_signals():
    fake = MagicMock()
    fake.worker_process_init = _FakeSignal()
    return fake


class TestInstallConnectsSignal:
    def test_install_connects_worker_process_init_with_strong_ref(
        self, fake_celery_signals
    ):
        """
        Given a Celery app,
        When install() is called,
        Then exactly one receiver is connected to worker_process_init
        with weak=False (so the closure survives GC).
        """
        with patch.dict(
            "sys.modules", {"celery": MagicMock(), "celery.signals": fake_celery_signals}
        ):
            from snitchbot.integrations.celery import install
            install(MagicMock(), service="my-worker")

            sig = fake_celery_signals.worker_process_init
            assert len(sig.receivers) == 1
            _fn, weak = sig.receivers[0]
            assert weak is False


class TestInstallReceiverCallsSnitchbotInit:
    def test_receiver_calls_init_with_role_worker(self, fake_celery_signals):
        """
        Given install() registered a receiver,
        When the receiver fires (simulating a worker post-fork),
        Then snitchbot.init is called with role='worker' by default.
        """
        with patch.dict(
            "sys.modules", {"celery": MagicMock(), "celery.signals": fake_celery_signals}
        ), patch("snitchbot.init") as mock_init:
            from snitchbot.integrations.celery import install
            install(MagicMock(), service="my-worker")

            receiver, _weak = fake_celery_signals.worker_process_init.receivers[0]
            receiver()  # signal dispatch passes kwargs; we ignore them
            mock_init.assert_called_once_with("my-worker", role="worker")

    def test_explicit_role_override_forwarded(self, fake_celery_signals):
        """
        Given install() called with role="beat",
        When the receiver fires,
        Then snitchbot.init is called with role="beat" (caller wins).
        """
        with patch.dict(
            "sys.modules", {"celery": MagicMock(), "celery.signals": fake_celery_signals}
        ), patch("snitchbot.init") as mock_init:
            from snitchbot.integrations.celery import install
            install(MagicMock(), service="my-worker", role="beat")

            receiver, _ = fake_celery_signals.worker_process_init.receivers[0]
            receiver()
            mock_init.assert_called_once_with("my-worker", role="beat")
