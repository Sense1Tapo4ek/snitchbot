"""Unit tests for SidecarSession.

No mocks — pure domain logic only.
"""
import time

from snitchbot.sidecar.session.domain.session_agg import SidecarSession


class TestInitialState:
    def test_last_activity_defaults_to_started_at(self):
        """
        Given a SidecarSession initialised with a started_at timestamp
          and no explicit last_activity_at,
        When the session is created,
        Then last_activity_at equals started_at.
        """
        # Arrange / Act
        now = time.monotonic()
        session = SidecarSession(started_at=now)

        # Assert
        assert session.last_activity_at == now

    def test_first_hello_received_defaults_to_false(self):
        """
        Given a freshly created SidecarSession,
        When checking first_hello_received,
        Then it is False.
        """
        # Arrange / Act
        session = SidecarSession(started_at=time.monotonic())

        # Assert
        assert session.first_hello_received is False

    def test_shutdown_requested_defaults_to_false(self):
        """
        Given a freshly created SidecarSession,
        When checking shutdown_requested,
        Then it is False.
        """
        # Arrange / Act
        session = SidecarSession(started_at=time.monotonic())

        # Assert
        assert session.shutdown_requested is False


class TestMarkActivity:
    def test_mark_activity_advances_last_activity_at(self):
        """
        Given a SidecarSession created in the past,
        When mark_activity() is called,
        Then last_activity_at is strictly greater than the initial value.
        """
        # Arrange
        old_time = time.monotonic() - 10.0
        session = SidecarSession(started_at=old_time)
        initial = session.last_activity_at

        # Act
        session.mark_activity()

        # Assert
        assert session.last_activity_at > initial


class TestMarkFirstHello:
    def test_mark_first_hello_sets_flag_and_advances_activity(self):
        """
        Given a SidecarSession that has not received a hello,
        When mark_first_hello() is called,
        Then first_hello_received is True and last_activity_at advances.
        """
        # Arrange
        old_time = time.monotonic() - 10.0
        session = SidecarSession(started_at=old_time)
        initial_activity = session.last_activity_at

        # Act
        session.mark_first_hello()

        # Assert
        assert session.first_hello_received is True
        assert session.last_activity_at > initial_activity


class TestRequestShutdown:
    def test_request_shutdown_sets_flag(self):
        """
        Given a running SidecarSession,
        When request_shutdown() is called,
        Then shutdown_requested becomes True.
        """
        # Arrange
        session = SidecarSession(started_at=time.monotonic())
        assert session.shutdown_requested is False

        # Act
        session.request_shutdown()

        # Assert
        assert session.shutdown_requested is True


class TestIdleSeconds:
    def test_idle_seconds_is_non_negative_and_monotonically_increasing(self):
        """
        Given a SidecarSession created a moment ago,
        When idle_seconds() is called twice with a small sleep between,
        Then the second reading is >= the first and both are non-negative.
        """
        # Arrange
        session = SidecarSession(started_at=time.monotonic())

        # Act
        first = session.idle_seconds()
        time.sleep(0.01)
        second = session.idle_seconds()

        # Assert
        assert first >= 0.0
        assert second >= first
