"""Unit tests for command and meta budgets — Task 9.8.

Spec: interactive §13.
Invariants: rate-limit on command responses.
"""


from snitchbot.sidecar.telegram_io.domain.command_budget_vo import CommandBudget
from snitchbot.sidecar.telegram_io.domain.meta_budget_vo import MetaBudget

# ---------------------------------------------------------------------------
# test_command_budget_10_per_min
# ---------------------------------------------------------------------------


def test_command_budget_10_per_min():
    """
    Given a fresh CommandBudget,
    When 10 tokens are consumed,
    Then the 11th acquire returns False (rate-limited).
    """
    budget = CommandBudget()
    assert budget._capacity == 10
    # refill rate: 1 token / 6 sec -> 1/6 tokens/sec
    assert abs(budget._refill_rate - 1 / 6) < 1e-9

    for _ in range(10):
        assert budget.acquire() is True
    assert budget.acquire() is False


# ---------------------------------------------------------------------------
# test_meta_budget_20_per_min
# ---------------------------------------------------------------------------


def test_meta_budget_20_per_min():
    """
    Given a fresh MetaBudget,
    When 20 tokens are consumed,
    Then the 21st acquire returns False.
    """
    budget = MetaBudget()
    assert budget._capacity == 20
    # refill rate: 1 token / 3 sec -> 1/3 tokens/sec
    assert abs(budget._refill_rate - 1 / 3) < 1e-9

    for _ in range(20):
        assert budget.acquire() is True
    assert budget.acquire() is False


# ---------------------------------------------------------------------------
# test_rate_limited_read_only_response
# ---------------------------------------------------------------------------


def test_rate_limited_read_only_response():
    """
    Given CommandBudget exhausted,
    When rate_limited_message() is called for a read-only command,
    Then the message contains '⏳' and 'retry in'.
    """
    budget = CommandBudget()
    # drain
    for _ in range(10):
        budget.acquire()

    msg = budget.rate_limited_message("status")
    assert "⏳" in msg
    assert "retry in" in msg.lower()
    # no 'not processed' for read-only
    assert "not processed" not in msg.lower()


# ---------------------------------------------------------------------------
# test_rate_limited_stateful_response_says_not_processed
# ---------------------------------------------------------------------------


def test_rate_limited_stateful_response_says_not_processed():
    """
    Given CommandBudget exhausted,
    When rate_limited_message() is called for stateful command (/mute),
    Then the message contains 'not processed'.
    """
    budget = CommandBudget()
    for _ in range(10):
        budget.acquire()

    msg = budget.rate_limited_message("mute")
    assert "⏳" in msg
    assert "not processed" in msg.lower()


# ---------------------------------------------------------------------------
# test_meta_budget_exhaustion_silent_drop
# ---------------------------------------------------------------------------


def test_meta_budget_exhaustion_silent_drop():
    """
    Given MetaBudget exhausted,
    When acquire() is called again,
    Then False is returned (silent drop — no exception, no message).
    """
    budget = MetaBudget()
    for _ in range(20):
        budget.acquire()

    result = budget.acquire()
    assert result is False
