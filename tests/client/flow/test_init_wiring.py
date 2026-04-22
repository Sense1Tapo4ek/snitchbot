"""Test that init() wires real transport and _send_event_fn delivers events."""
from unittest.mock import MagicMock, patch

import pytest


class TestWatchSlowWiring:
    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset public_api module state and watch_slow module state between tests."""
        from snitchbot.client.ports.driving import public_api as pa
        old = (pa._initialized, pa._initialized_pid, pa._stored_config, pa._send_event_fn)
        pa._initialized = False
        pa._initialized_pid = None
        pa._stored_config = None
        pa._send_event_fn = None

        from snitchbot.client.adapters.driving.instrumentation import watch_slow as _ws_mod
        old_ws = _ws_mod._module_send_event
        _ws_mod._module_send_event = None

        yield

        pa._initialized, pa._initialized_pid, pa._stored_config, pa._send_event_fn = old
        _ws_mod._module_send_event = old_ws

        from snitchbot.client.adapters.driving.excepthooks.asyncio_patch import (
            uninstall as uninstall_asyncio,
        )
        from snitchbot.client.adapters.driving.excepthooks.sys_excepthook import (
            uninstall as uninstall_sys,
        )
        from snitchbot.client.adapters.driving.excepthooks.threading_excepthook import (
            uninstall as uninstall_threading,
        )
        from snitchbot.client.adapters.driving.signals.signal_handlers import (
            uninstall as uninstall_signals,
        )
        uninstall_asyncio()
        uninstall_sys()
        uninstall_threading()
        uninstall_signals()

    @patch("snitchbot.client.ports.driving.public_api.SocketPathDiscovery")
    @patch("snitchbot.client.ports.driving.public_api.SubprocessSidecarSpawner")
    @patch("snitchbot.client.ports.driving.public_api.UnixDgramTransport")
    @patch("snitchbot.client.ports.driving.public_api.SendEventUseCase")
    @patch("snitchbot.client.ports.driving.public_api.InitializeClientUseCase")
    def test_watch_slow_module_send_wired_after_init(
        self, MockInitUC, MockSendUC, MockTransport, MockSpawner, MockDiscovery
    ):
        """
        Given a clean init state,
        When init() is called,
        Then watch_slow._module_send_event is not None.
        """
        from snitchbot.client.ports.driving.public_api import init
        init("test-svc", token="tok", chat_id="123")

        from snitchbot.client.adapters.driving.instrumentation import watch_slow as _ws_mod
        assert _ws_mod._module_send_event is not None

    @patch("snitchbot.client.ports.driving.public_api.SocketPathDiscovery")
    @patch("snitchbot.client.ports.driving.public_api.SubprocessSidecarSpawner")
    @patch("snitchbot.client.ports.driving.public_api.UnixDgramTransport")
    @patch("snitchbot.client.ports.driving.public_api.SendEventUseCase")
    @patch("snitchbot.client.ports.driving.public_api.InitializeClientUseCase")
    def test_watchdog_thread_started_after_init(
        self, MockInitUC, MockSendUC, MockTransport, MockSpawner, MockDiscovery
    ):
        """
        Given a clean init state,
        When init() is called,
        Then at least one WatchdogThread daemon is alive.
        """
        import threading

        threads_before = {t.ident for t in threading.enumerate() if t.name == "snitchbot-watchdog"}

        from snitchbot.client.ports.driving.public_api import init
        init("test-svc", token="tok", chat_id="123")

        threads_after = [t for t in threading.enumerate() if t.name == "snitchbot-watchdog"]
        new_watchdogs = [t for t in threads_after if t.ident not in threads_before]
        assert len(new_watchdogs) >= 1
        assert all(t.daemon is True for t in new_watchdogs)
        assert all(t.is_alive() for t in new_watchdogs)


class TestInitWiring:
    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset public_api module state between tests."""
        from snitchbot.client.ports.driving import public_api as pa
        old = (pa._initialized, pa._initialized_pid, pa._stored_config, pa._send_event_fn)
        pa._initialized = False
        pa._initialized_pid = None
        pa._stored_config = None
        pa._send_event_fn = None
        yield
        pa._initialized, pa._initialized_pid, pa._stored_config, pa._send_event_fn = old
        # Uninstall all hooks to avoid recursive wrapping across tests
        from snitchbot.client.adapters.driving.excepthooks.asyncio_patch import (
            uninstall as uninstall_asyncio,
        )
        from snitchbot.client.adapters.driving.excepthooks.sys_excepthook import (
            uninstall as uninstall_sys,
        )
        from snitchbot.client.adapters.driving.excepthooks.threading_excepthook import (
            uninstall as uninstall_threading,
        )
        from snitchbot.client.adapters.driving.signals.signal_handlers import (
            uninstall as uninstall_signals,
        )
        uninstall_asyncio()
        uninstall_sys()
        uninstall_threading()
        uninstall_signals()

    @patch("snitchbot.client.ports.driving.public_api.SocketPathDiscovery")
    @patch("snitchbot.client.ports.driving.public_api.SubprocessSidecarSpawner")
    @patch("snitchbot.client.ports.driving.public_api.UnixDgramTransport")
    @patch("snitchbot.client.ports.driving.public_api.SendEventUseCase")
    @patch("snitchbot.client.ports.driving.public_api.InitializeClientUseCase")
    def test_init_creates_transport_and_send_uc(
        self, MockInitUC, MockSendUC, MockTransport, MockSpawner, MockDiscovery
    ):
        """
        Given valid token and chat_id,
        When init() is called,
        Then InitializeClientUseCase is constructed and called,
        and _send_event_fn is set to SendEventUseCase.__call__.
        """
        from snitchbot.client.domain.client_state_agg import ClientState
        MockInitUC.return_value.return_value = ClientState.CONNECTED

        from snitchbot.client.ports.driving.public_api import init
        init("test-svc", token="tok", chat_id="123")

        MockInitUC.return_value.assert_called_once()
        MockSendUC.assert_called_once()

    @patch("snitchbot.client.ports.driving.public_api.SocketPathDiscovery")
    @patch("snitchbot.client.ports.driving.public_api.SubprocessSidecarSpawner")
    @patch("snitchbot.client.ports.driving.public_api.UnixDgramTransport")
    @patch("snitchbot.client.ports.driving.public_api.SendEventUseCase")
    @patch("snitchbot.client.ports.driving.public_api.InitializeClientUseCase")
    def test_notify_after_init_calls_send_uc(
        self, MockInitUC, MockSendUC, MockTransport, MockSpawner, MockDiscovery
    ):
        """
        Given init() has completed,
        When notify() is called,
        Then _send_event_fn is invoked with the event dict.
        """
        from snitchbot.client.domain.client_state_agg import ClientState
        MockInitUC.return_value.return_value = ClientState.CONNECTED
        mock_send = MagicMock()
        MockSendUC.return_value = mock_send

        from snitchbot.client.ports.driving.public_api import init, notify
        init("test-svc", token="tok", chat_id="123")
        notify("hello world")

        # send_uc is called for the startup lifecycle event AND for notify()
        assert mock_send.call_count >= 1
        # Find the custom event call
        custom_calls = [
            c for c in mock_send.call_args_list
            if c[0][0].get("kind") == "custom"
        ]
        assert len(custom_calls) == 1
        event = custom_calls[0][0][0]
        assert event["payload"]["text"] == "hello world"

    @patch("snitchbot.client.ports.driving.public_api.SocketPathDiscovery")
    @patch("snitchbot.client.ports.driving.public_api.SubprocessSidecarSpawner")
    @patch("snitchbot.client.ports.driving.public_api.UnixDgramTransport")
    @patch("snitchbot.client.ports.driving.public_api.SendEventUseCase")
    @patch("snitchbot.client.ports.driving.public_api.InitializeClientUseCase")
    def test_init_failure_goes_degraded_still_initialized(
        self, MockInitUC, MockSendUC, MockTransport, MockSpawner, MockDiscovery
    ):
        """
        Given InitializeClientUseCase raises,
        When init() is called,
        Then no exception propagates (I2) and _initialized is True (degraded mode).
        """
        MockInitUC.return_value.side_effect = OSError("socket failed")

        from snitchbot.client.ports.driving import public_api as pa
        pa.init("test-svc", token="tok", chat_id="123")

        assert pa._initialized is True
        assert pa._stats.internal_errors >= 1
