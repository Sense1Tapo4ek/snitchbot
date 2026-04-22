"""Tests that snitchbot.integrations exports are importable via __init__.py."""
import pytest


class TestIntegrationsImport:
    def test_import_logging_handler(self):
        """
        Given snitchbot.integrations package,
        When importing SnitchbotLoggingHandler,
        Then it is accessible without error.
        """
        from snitchbot.integrations import SnitchbotLoggingHandler
        assert SnitchbotLoggingHandler is not None

    def test_import_structlog_processor(self):
        """
        Given snitchbot.integrations package,
        When importing make_structlog_processor,
        Then it is accessible without error.
        """
        from snitchbot.integrations import make_structlog_processor
        assert make_structlog_processor is not None

    def test_all_contains_expected_symbols(self):
        """
        Given snitchbot.integrations package,
        When accessing __all__,
        Then it contains both exported symbols.
        """
        import snitchbot.integrations as pkg
        assert "SnitchbotLoggingHandler" in pkg.__all__
        assert "make_structlog_processor" in pkg.__all__
