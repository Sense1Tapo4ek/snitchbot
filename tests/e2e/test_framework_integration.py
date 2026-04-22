"""Integration tests: snitchbot works correctly inside FastAPI, Litestar, Flask.

All tests use disabled=True so no real Telegram token is needed.
watch_slow is configured with a generous threshold (5 s) so fast test
responses never trigger slow-call emission.
"""
import pytest

fastapi = pytest.importorskip("fastapi")
litestar = pytest.importorskip("litestar")
flask = pytest.importorskip("flask")


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------


class TestFastAPIIntegration:
    @pytest.fixture()
    def fastapi_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import snitchbot

        app = FastAPI()

        # disabled=True — verifies zero overhead, no Telegram token needed
        snitchbot.init("test-fastapi", token="test", chat_id="123", disabled=True)

        @app.get("/")
        async def root() -> dict:
            return {"ok": True}

        @app.get("/notify")
        async def notify() -> dict:
            snitchbot.notify("test", severity="warning")
            return {"sent": True}

        @app.get("/slow")
        @snitchbot.watch_slow(threshold_ms=5000)
        async def slow() -> dict:
            return {"fast": True}

        @app.get("/context")
        async def context() -> dict:
            with snitchbot.request_context(trace_id="t-1", user="u"):
                snitchbot.notify("ctx test")
            return {"ctx": True}

        @app.get("/crash")
        async def crash() -> dict:
            raise ValueError("boom")

        return TestClient(app, raise_server_exceptions=False)

    def test_root_ok(self, fastapi_client) -> None:
        """GET / returns 200."""
        r = fastapi_client.get("/")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_notify_no_crash(self, fastapi_client) -> None:
        """snitchbot.notify() inside a handler doesn't raise (P1)."""
        r = fastapi_client.get("/notify")
        assert r.status_code == 200
        assert r.json() == {"sent": True}

    def test_watch_slow_preserves_response(self, fastapi_client) -> None:
        """@watch_slow doesn't interfere with the handler return value."""
        r = fastapi_client.get("/slow")
        assert r.status_code == 200
        assert r.json() == {"fast": True}

    def test_request_context_no_crash(self, fastapi_client) -> None:
        """request_context() CM inside a handler doesn't crash."""
        r = fastapi_client.get("/context")
        assert r.status_code == 200
        assert r.json() == {"ctx": True}

    def test_crash_propagates(self, fastapi_client) -> None:
        """snitchbot doesn't swallow application exceptions."""
        r = fastapi_client.get("/crash")
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# Litestar
# ---------------------------------------------------------------------------


class TestLitestarIntegration:
    @pytest.fixture()
    def litestar_client(self):
        from litestar import Litestar, get
        from litestar.testing import TestClient

        import snitchbot

        snitchbot.init("test-litestar", token="test", chat_id="123", disabled=True)

        @get("/")
        async def root() -> dict:
            return {"ok": True}

        @get("/notify")
        async def notify() -> dict:
            snitchbot.notify("test")
            return {"sent": True}

        @get("/slow")
        @snitchbot.watch_slow(threshold_ms=5000)
        async def slow() -> dict:
            return {"fast": True}

        @get("/context")
        async def context() -> dict:
            with snitchbot.request_context(trace_id="t-2", user="u2"):
                snitchbot.notify("litestar ctx test")
            return {"ctx": True}

        app = Litestar([root, notify, slow, context])
        return TestClient(app)

    def test_root_ok(self, litestar_client) -> None:
        """GET / returns 200."""
        r = litestar_client.get("/")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_notify_no_crash(self, litestar_client) -> None:
        """snitchbot.notify() inside a Litestar handler doesn't raise (P1)."""
        r = litestar_client.get("/notify")
        assert r.status_code == 200
        assert r.json() == {"sent": True}

    def test_watch_slow_preserves_response(self, litestar_client) -> None:
        """@watch_slow doesn't interfere with the handler return value."""
        r = litestar_client.get("/slow")
        assert r.status_code == 200
        assert r.json() == {"fast": True}

    def test_request_context_no_crash(self, litestar_client) -> None:
        """request_context() CM inside a Litestar handler doesn't crash."""
        r = litestar_client.get("/context")
        assert r.status_code == 200
        assert r.json() == {"ctx": True}


# ---------------------------------------------------------------------------
# Flask
# ---------------------------------------------------------------------------


class TestFlaskIntegration:
    @pytest.fixture()
    def flask_client(self):
        from flask import Flask

        import snitchbot

        app = Flask(__name__)
        snitchbot.init("test-flask", token="test", chat_id="123", disabled=True)

        @app.route("/")
        def root():
            return {"ok": True}

        @app.route("/notify")
        def notify():
            snitchbot.notify("test")
            return {"sent": True}

        @app.route("/slow")
        @snitchbot.watch_slow(threshold_ms=5000)
        def slow():
            return {"fast": True}

        @app.route("/context")
        def context():
            with snitchbot.request_context(trace_id="t-3", user="u3"):
                snitchbot.notify("flask ctx test")
            return {"ctx": True}

        @app.route("/crash")
        def crash():
            raise ValueError("boom")

        return app.test_client()

    def test_root_ok(self, flask_client) -> None:
        """GET / returns 200."""
        r = flask_client.get("/")
        assert r.status_code == 200

    def test_notify_no_crash(self, flask_client) -> None:
        """snitchbot.notify() inside a Flask handler doesn't raise (P1)."""
        r = flask_client.get("/notify")
        assert r.status_code == 200

    def test_watch_slow_sync(self, flask_client) -> None:
        """@watch_slow works on sync Flask route functions."""
        r = flask_client.get("/slow")
        assert r.status_code == 200

    def test_request_context_no_crash(self, flask_client) -> None:
        """request_context() CM inside a Flask handler doesn't crash."""
        r = flask_client.get("/context")
        assert r.status_code == 200

    def test_crash_propagates(self, flask_client) -> None:
        """snitchbot doesn't swallow Flask application exceptions."""
        r = flask_client.get("/crash")
        assert r.status_code == 500
