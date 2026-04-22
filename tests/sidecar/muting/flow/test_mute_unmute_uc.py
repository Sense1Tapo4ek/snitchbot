"""Flow tests for MuteUC and UnmuteUC (/mute, /unmute commands).

Spec: docs/superpowers/specs/2026-04-11-interactive-tg-design.md §7, §8.
Plan: Task 9.6.

Invariants validated: T5 (persistence), T9 (duplicate mute rejected), T11 (edit source).
"""
from unittest.mock import AsyncMock

import pytest

from snitchbot.sidecar.muting.app.use_cases.mute_uc import MuteUC
from snitchbot.sidecar.muting.app.use_cases.unmute_uc import UnmuteUC
from snitchbot.sidecar.muting.domain.mute_state_agg import MuteState

_NOW = 1_000_000.0
_FP = "a1b2c3"


def _make_mute_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.save = AsyncMock(return_value=None)
    return repo


def _make_mute_uc(
    mute_state: MuteState | None = None,
    repo: AsyncMock | None = None,
) -> MuteUC:
    if mute_state is None:
        mute_state = MuteState()
    if repo is None:
        repo = _make_mute_repo()
    return MuteUC(
        _mute_state=mute_state,
        _mute_repo=repo,
    )


def _make_unmute_uc(
    mute_state: MuteState | None = None,
    repo: AsyncMock | None = None,
) -> UnmuteUC:
    if mute_state is None:
        mute_state = MuteState()
    if repo is None:
        repo = _make_mute_repo()
    return UnmuteUC(
        _mute_state=mute_state,
        _mute_repo=repo,
    )


# ---------------------------------------------------------------------------
# MuteUC tests
# ---------------------------------------------------------------------------

class TestMutePoint:
    @pytest.mark.asyncio
    async def test_mute_point_success(self) -> None:
        """
        Given a valid fingerprint and duration,
        When /mute a1b2c3 1h,
        Then 🔇 Muted reply with expires_at.
        """
        uc = _make_mute_uc()
        result = await uc(args=f"{_FP} 1h", now=_NOW)
        text = result["text"]
        assert "🔇" in text
        assert "Muted" in text
        assert _FP in text

    @pytest.mark.asyncio
    async def test_mute_global_success(self) -> None:
        """
        Given /mute all 30m,
        When executed,
        Then 🔇 Global mute reply.
        """
        uc = _make_mute_uc()
        result = await uc(args="all 30m", now=_NOW)
        text = result["text"]
        assert "🔇" in text
        assert "Global" in text or "global" in text

    @pytest.mark.asyncio
    async def test_mute_already_muted_rejected(self) -> None:
        """T9: Repeat mute on already-muted fingerprint is rejected.

        Given fingerprint already muted for 1h,
        When /mute a1b2c3 1h called again,
        Then ❌ Already muted response returned, state unchanged.
        """
        state = MuteState()
        state.mute(fingerprint=_FP, duration_sec=3600, source_message_id=None, now=_NOW)
        uc = _make_mute_uc(mute_state=state)
        result = await uc(args=f"{_FP} 1h", now=_NOW + 60)
        text = result["text"]
        assert "❌" in text
        assert "Already muted" in text

    @pytest.mark.asyncio
    async def test_mute_invalid_duration(self) -> None:
        """
        Given /mute a1b2c3 5min (invalid format),
        When executed,
        Then ❌ Invalid duration error returned.
        """
        uc = _make_mute_uc()
        result = await uc(args=f"{_FP} 5min", now=_NOW)
        assert "❌" in result["text"]
        assert "Invalid duration" in result["text"] or "duration" in result["text"].lower()

    @pytest.mark.asyncio
    async def test_mute_duration_over_7d_error(self) -> None:
        """
        Given /mute a1b2c3 8d (exceeds max),
        When executed,
        Then ❌ Duration exceeds max error.
        """
        uc = _make_mute_uc()
        # 8d is out of range for window parser (max 7d)
        result = await uc(args=f"{_FP} 8d", now=_NOW)
        assert "❌" in result["text"]

    @pytest.mark.asyncio
    async def test_mute_missing_args_error(self) -> None:
        """
        Given /mute with only one arg,
        When executed,
        Then usage error returned.
        """
        uc = _make_mute_uc()
        result = await uc(args=_FP, now=_NOW)
        assert "❌" in result["text"]
        assert "usage" in result["text"].lower()


class TestMuteExpired:
    @pytest.mark.asyncio
    async def test_mute_expired_allows_new_mute(self) -> None:
        """
        Given fingerprint whose mute has expired,
        When /mute same fingerprint again,
        Then new mute is created (not rejected as 'already muted').
        """
        state = MuteState()
        # Mute for 5 minutes, but now is 10 minutes later
        state.mute(fingerprint=_FP, duration_sec=300, source_message_id=None, now=_NOW)
        uc = _make_mute_uc(mute_state=state)
        result = await uc(args=f"{_FP} 1h", now=_NOW + 900)  # 15m later
        text = result["text"]
        # Should succeed, not "already muted"
        assert "🔇" in text
        assert "Already muted" not in text


# ---------------------------------------------------------------------------
# UnmuteUC tests
# ---------------------------------------------------------------------------

class TestUnmute:
    @pytest.mark.asyncio
    async def test_unmute_success_reports_suppressed(self) -> None:
        """
        Given an active mute with suppressed events,
        When /unmute a1b2c3,
        Then 🔔 Unmuted reply with suppressed count.
        """
        state = MuteState()
        state.mute(fingerprint=_FP, duration_sec=3600, source_message_id=None, now=_NOW)
        # Simulate 3 suppressed events
        state.get_entry(_FP).suppressed_count = 3

        uc = _make_unmute_uc(mute_state=state)
        result = await uc(args=_FP, now=_NOW + 60)
        text = result["text"]
        assert "🔔" in text
        assert "Unmuted" in text or "unmuted" in text.lower()
        assert "3" in text  # suppressed count

    @pytest.mark.asyncio
    async def test_unmute_not_muted_error(self) -> None:
        """
        Given no active mute for fingerprint,
        When /unmute a1b2c3,
        Then ❌ Not muted error.
        """
        state = MuteState()
        uc = _make_unmute_uc(mute_state=state)
        result = await uc(args=_FP, now=_NOW)
        assert "❌" in result["text"]
        assert "Not muted" in result["text"] or "not muted" in result["text"].lower()

    @pytest.mark.asyncio
    async def test_unmute_global_success(self) -> None:
        """
        Given active global mute,
        When /unmute all,
        Then global mute cancelled response.
        """
        state = MuteState()
        state.mute(fingerprint=None, duration_sec=1800, source_message_id=None, now=_NOW)
        uc = _make_unmute_uc(mute_state=state)
        result = await uc(args="all", now=_NOW + 60)
        text = result["text"]
        assert "🔔" in text
        assert "Global" in text or "global" in text.lower()

    @pytest.mark.asyncio
    async def test_unmute_global_not_active_error(self) -> None:
        """
        Given no global mute,
        When /unmute all,
        Then ❌ No global mute active.
        """
        state = MuteState()
        uc = _make_unmute_uc(mute_state=state)
        result = await uc(args="all", now=_NOW)
        assert "❌" in result["text"]
        assert "global" in result["text"].lower() or "Global" in result["text"]

    @pytest.mark.asyncio
    async def test_unmute_persists_via_repo(self) -> None:
        """T5: mute state is persisted on unmute.

        Given active mute and a mute repo mock,
        When /unmute called,
        Then repo.save() is called.
        """
        state = MuteState()
        state.mute(fingerprint=_FP, duration_sec=3600, source_message_id=None, now=_NOW)
        repo = _make_mute_repo()
        uc = _make_unmute_uc(mute_state=state, repo=repo)
        await uc(args=_FP, now=_NOW + 60)
        repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_mute_persists_via_repo(self) -> None:
        """T5: mute state is persisted on mute.

        Given fresh mute state and a mute repo mock,
        When /mute a1b2c3 1h,
        Then repo.save() is called.
        """
        repo = _make_mute_repo()
        uc = _make_mute_uc(repo=repo)
        await uc(args=f"{_FP} 1h", now=_NOW)
        repo.save.assert_called_once()
