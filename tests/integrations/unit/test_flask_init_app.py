"""Unit tests for snitchbot.integrations.flask.init_app."""
from unittest.mock import MagicMock, patch

import pytest

from snitchbot.integrations.flask import init_app


class _FakeFlaskApp:
    """Minimal Flask-app double that records before_request callbacks."""

    def __init__(self) -> None:
        self.before_request_callbacks: list = []

    def before_request(self, fn):  # noqa: D401 — match Flask API
        self.before_request_callbacks.append(fn)
        return fn


@pytest.fixture(autouse=True)
def _reset_module_state():
    """init_app uses module-level globals; reset between tests."""
    from snitchbot.integrations import flask as f
    f._inited = False
    yield
    f._inited = False


class TestInitAppRegistersCallback:
    def test_init_app_registers_one_before_request_callback(self):
        """
        Given a Flask app,
        When init_app(app, service=...) is called,
        Then exactly one before_request callback is registered.
        """
        app = _FakeFlaskApp()
        init_app(app, service="orders-api", role="web")
        assert len(app.before_request_callbacks) == 1


class TestInitAppCallsSnitchbotOnce:
    def test_first_request_calls_snitchbot_init(self):
        """
        Given init_app installed a before_request guard,
        When the guard fires once,
        Then snitchbot.init is called with the configured args.
        """
        app = _FakeFlaskApp()
        with patch("snitchbot.init") as mock_init:
            init_app(app, service="orders-api", role="web")
            app.before_request_callbacks[0]()
            mock_init.assert_called_once_with("orders-api", role="web")

    def test_second_request_does_not_reinit(self):
        """
        Given snitchbot was inited on first request,
        When the guard fires again,
        Then snitchbot.init is NOT called a second time.
        """
        app = _FakeFlaskApp()
        with patch("snitchbot.init") as mock_init:
            init_app(app, service="orders-api")
            app.before_request_callbacks[0]()
            app.before_request_callbacks[0]()
            assert mock_init.call_count == 1


class TestInitAppForwardsKwargs:
    def test_arbitrary_init_kwargs_forwarded(self):
        """
        Given init_app called with extra kwargs,
        When the guard fires,
        Then those kwargs are forwarded to snitchbot.init verbatim.
        """
        app = _FakeFlaskApp()
        with patch("snitchbot.init") as mock_init:
            init_app(app, service="x", role="worker", live_dashboard=False)
            app.before_request_callbacks[0]()
            mock_init.assert_called_once_with("x", role="worker", live_dashboard=False)
