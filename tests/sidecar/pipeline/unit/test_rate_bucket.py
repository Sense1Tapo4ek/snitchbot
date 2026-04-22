"""Unit tests for RateBucket — Task 6.4.

Invariants validated: RL1, RL2, RL8.
"""
import time

from snitchbot.sidecar.pipeline.domain.rate_bucket_vo import RateBucket
from snitchbot.sidecar.pipeline.domain.services.critical_ceiling_policy_service import (
    CriticalCeilingPolicy,
)

# ---------------------------------------------------------------------------
# test_main_bucket_size_30_refill_0_5_per_sec  (RL1)
# ---------------------------------------------------------------------------

def test_main_bucket_size_30_refill_0_5_per_sec():
    """
    RL1: main bucket has capacity 30, refill rate 0.5 tokens/sec.
    Defaults must match these exact values.
    """
    bucket = RateBucket()
    assert bucket._capacity == 30
    assert bucket._refill_rate == 0.5


# ---------------------------------------------------------------------------
# test_token_consumed_on_each_acquire
# ---------------------------------------------------------------------------

def test_token_consumed_on_each_acquire():
    """
    Each successful non-critical acquire consumes exactly one token
    from the main bucket.
    """
    bucket = RateBucket(capacity=5, refill_rate=0.0)  # no refill for determinism
    for _ in range(5):
        assert bucket.acquire(is_critical=False) is True
    # bucket empty
    assert bucket.acquire(is_critical=False) is False


# ---------------------------------------------------------------------------
# test_critical_bypass_main_bucket  (RL2)
# ---------------------------------------------------------------------------

def test_critical_bypass_main_bucket():
    """
    RL2: critical events bypass the main bucket.
    Even with zero tokens remaining, critical acquire returns True.
    """
    bucket = RateBucket(capacity=3, refill_rate=0.0)
    # drain main bucket
    for _ in range(3):
        bucket.acquire(is_critical=False)
    assert bucket.acquire(is_critical=False) is False  # confirm empty

    # critical bypasses
    assert bucket.acquire(is_critical=True) is True


# ---------------------------------------------------------------------------
# test_critical_ceiling_60_per_min  (RL2)
# ---------------------------------------------------------------------------

def test_critical_ceiling_60_per_min():
    """
    RL2: ceiling 60 critical per minute.
    After 60 successful critical acquires within the same window,
    the 61st returns False (dropped).
    """
    bucket = RateBucket(capacity=30, refill_rate=0.0)
    # drain main bucket so we stay in critical path only
    for _ in range(30):
        bucket.acquire(is_critical=False)

    for _ in range(60):
        result = bucket.acquire(is_critical=True)
        assert result is True, "First 60 criticals must be allowed"

    # 61st must be blocked
    assert bucket.acquire(is_critical=True) is False


# ---------------------------------------------------------------------------
# test_bucket_empty_returns_false_until_refill
# ---------------------------------------------------------------------------

def test_bucket_empty_returns_false_until_refill():
    """
    When the bucket is empty, non-critical acquires return False.
    After enough time passes for at least one refill, acquires succeed again.
    """
    # Use a very fast refill rate for test speed (1 token/ms)
    bucket = RateBucket(capacity=1, refill_rate=1000.0)
    assert bucket.acquire(is_critical=False) is True  # consume the single token
    assert bucket.acquire(is_critical=False) is False  # empty

    # Wait 2ms so at least 2 tokens refill (but capacity is 1, so only 1)
    time.sleep(0.002)
    assert bucket.acquire(is_critical=False) is True  # refilled


# ---------------------------------------------------------------------------
# test_refill_over_time
# ---------------------------------------------------------------------------

def test_refill_over_time():
    """
    After 2 seconds with refill_rate=0.5/sec, at least 1 token is refilled.
    """
    bucket = RateBucket(capacity=30, refill_rate=0.5)
    # drain completely
    for _ in range(30):
        bucket.acquire(is_critical=False)
    assert bucket.acquire(is_critical=False) is False

    # 2 seconds -> 1 token refilled (0.5 * 2 = 1.0)
    time.sleep(2.05)
    assert bucket.acquire(is_critical=False) is True


# ---------------------------------------------------------------------------
# test_answer_callback_query_does_not_consume  (RL8)
# ---------------------------------------------------------------------------

def test_answer_callback_query_does_not_consume():
    """
    RL8: answerCallbackQuery does not consume from the main bucket.
    Modelled as a pass-through — callers must NOT call acquire() for ACQ.
    This test validates the CriticalCeilingPolicy classification function:
    'answer_callback_query' action is classified as not consuming the bucket.
    """
    policy = CriticalCeilingPolicy()
    assert policy.consumes_main_bucket("answer_callback_query") is False
    assert policy.consumes_main_bucket("sendMessage") is True
    assert policy.consumes_main_bucket("editMessageText") is True
    assert policy.consumes_main_bucket("editMessageReplyMarkup") is True
