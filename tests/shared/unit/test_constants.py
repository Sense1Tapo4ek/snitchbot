"""Unit tests for shared constants (Task 1.1 / Phase 1 Shared Kernel §134)."""

from snitchbot.shared import constants


EXPECTED_CONSTANTS = {
    "DEDUP_WINDOW_SEC": 300,
    "VITALS_SAMPLE_SEC": 5,
    "FDS_SAMPLE_INTERVAL_SEC": 15,
    "WATCHDOG_THRESHOLD_MS": 500,
    "LIVE_MESSAGE_TICK_SEC": 10,
    "MAX_EVENT_SIZE": 8192,
    "TG_MESSAGE_LIMIT": 4096,
    "QUEUE_MAX": 256,
    "HANDSHAKE_RESPONSE_TIMEOUT_MS": 500,
    "SOCKET_POLL_TIMEOUT_SEC": 2.0,
    "PINGER_INTERVAL_SEC": 0.1,
    "WATCHDOG_COOLDOWN_SEC": 10,
    "WATCHDOG_CHECK_INTERVAL_SEC": 0.2,
    "WATCHDOG_ESCALATION_WINDOW_SEC": 60,
    "DEDUP_CACHE_MAX_BYTES": 10_485_760,
    "DEDUP_CACHE_MAX_ENTRIES": 10_000,
}


class TestConstantsValues:
    def test_all_expected_constants_defined(self):
        """
        Given the Phase 1 Shared Kernel §134 list,
        When importing `mylib.shared.constants`,
        Then every expected constant is present with the documented value.
        """
        for name, expected in EXPECTED_CONSTANTS.items():
            actual = getattr(constants, name, None)
            assert actual == expected, (
                f"constants.{name} expected {expected!r}, got {actual!r}"
            )

    def test_all_constants_are_plain_scalars(self):
        """
        Given the shared constants,
        When inspecting their types,
        Then each is an immutable scalar (int, float, or str).
        """
        for name in EXPECTED_CONSTANTS:
            value = getattr(constants, name)
            assert isinstance(value, (int, float, str)), (
                f"{name} must be a plain scalar, got {type(value).__name__}"
            )
            # Explicitly reject mutable containers.
            assert not isinstance(value, (list, dict, set, bytearray))

    def test_dedup_window_300(self):
        assert constants.DEDUP_WINDOW_SEC == 300

    def test_vitals_sample_5(self):
        assert constants.VITALS_SAMPLE_SEC == 5

    def test_fds_sample_interval_15(self):
        assert constants.FDS_SAMPLE_INTERVAL_SEC == 15

    def test_watchdog_threshold_500ms(self):
        assert constants.WATCHDOG_THRESHOLD_MS == 500

    def test_live_message_tick_10(self):
        assert constants.LIVE_MESSAGE_TICK_SEC == 10

    def test_max_event_size_8192(self):
        assert constants.MAX_EVENT_SIZE == 8192

    def test_tg_message_limit_4096(self):
        assert constants.TG_MESSAGE_LIMIT == 4096

    def test_queue_max_256(self):
        assert constants.QUEUE_MAX == 256

    def test_handshake_timeout_500ms(self):
        assert constants.HANDSHAKE_RESPONSE_TIMEOUT_MS == 500

    def test_socket_poll_timeout_2s(self):
        assert constants.SOCKET_POLL_TIMEOUT_SEC == 2.0
        assert isinstance(constants.SOCKET_POLL_TIMEOUT_SEC, float)

    def test_pinger_interval_100ms(self):
        assert constants.PINGER_INTERVAL_SEC == 0.1
        assert isinstance(constants.PINGER_INTERVAL_SEC, float)

    def test_watchdog_cooldown_10s(self):
        assert constants.WATCHDOG_COOLDOWN_SEC == 10

    def test_watchdog_check_interval_200ms(self):
        assert constants.WATCHDOG_CHECK_INTERVAL_SEC == 0.2
        assert isinstance(constants.WATCHDOG_CHECK_INTERVAL_SEC, float)

    def test_watchdog_escalation_window_60s(self):
        assert constants.WATCHDOG_ESCALATION_WINDOW_SEC == 60

    def test_dedup_cache_byte_cap_10mb(self):
        assert constants.DEDUP_CACHE_MAX_BYTES == 10_485_760

    def test_dedup_cache_entry_cap_10000(self):
        assert constants.DEDUP_CACHE_MAX_ENTRIES == 10_000


class TestSeparator:
    def test_separator_is_18_chars(self):
        """
        Given SEPARATOR is the canonical bot-message divider,
        When inspecting its length,
        Then it is exactly 18 characters (Invariant R1).
        """
        assert len(constants.SEPARATOR) == 18

    def test_separator_uses_heavy_horizontal_u2501(self):
        """
        Given SEPARATOR is the canonical bot-message divider,
        When inspecting each character,
        Then every character is U+2501 (BOX DRAWINGS HEAVY HORIZONTAL).
        """
        assert set(constants.SEPARATOR) == {"━"}
        assert all(ord(ch) == 0x2501 for ch in constants.SEPARATOR)

    def test_separator_value(self):
        assert constants.SEPARATOR == "━━━━━━━━━━━━━━━━━━"

    def test_separator_is_string(self):
        assert isinstance(constants.SEPARATOR, str)
