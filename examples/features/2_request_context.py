"""Feature demo: Request Context.

`snitchbot.request_context()` attaches trace IDs and metadata to ALL
telemetry events within its scope — without passing them down the stack.

Everything inside the `with` block shares the same context:
- `notify()` calls get the context
- `@watch_slow` alerts get the context
- crash reports get the context

This is how you connect Telegram alerts to specific HTTP requests,
background jobs, or user actions.

Expected Telegram output:
    🟠 notify · context-demo · 156afe
    User started checkout
    Details
        time     2026-04-17 12:53:41 UTC
        pid      1733454
        caller   examples/features/request_context.py:56 in handle_request()
    Extras
        cart_size   3
    Context
        trace_id  req-abc-123
        extras  {'user_id': 42, 'action': 'checkout'}

    🟠 slow call · context-demo · ee48d4
    __main__.call_payment_api took 201 ms (threshold 100 ms)
    Details
        time     2026-04-17 12:57:18 UTC
        pid      1738587
        is_async  true
        location  examples/features/2_request_context.py:40
    Context
        trace_id  req-abc-123
        extras  {'user_id': 42, 'action': 'checkout'}
"""
import asyncio

import snitchbot


@snitchbot.watch_slow(threshold_ms=100)
async def call_payment_api(amount: float) -> str:
    """Slow function — the alert will automatically include the context."""
    print(f"  Calling payment API for ${amount}...")
    await asyncio.sleep(0.2)
    return "txn-12345"


async def handle_request(request_id: str, user_id: int):
    """Simulates an HTTP handler."""
    print(f"Handling request {request_id}...")

    # Everything inside this block shares the context.
    # Works across await, create_task, and nested function calls.
    with snitchbot.request_context(
        trace_id=request_id,
        user_id=user_id,
        action="checkout",
    ):
        # This notify will have trace_id=req-abc-123
        snitchbot.notify(
            "User started checkout",
            severity="warning",
            extras={"cart_size": 3},
        )

        await asyncio.sleep(1)

        # This slow call alert will also have the same context
        txn_id = await call_payment_api(99.99)
        print(f"  Payment done: {txn_id}")

    await asyncio.sleep(3)
    print("Done. Check Telegram — both alerts share the same context.")


def main():
    snitchbot.init("context-demo", live_dashboard=False)
    asyncio.run(handle_request(request_id="req-abc-123", user_id=42))


if __name__ == "__main__":
    main()
