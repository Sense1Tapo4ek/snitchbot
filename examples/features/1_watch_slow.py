"""Feature demo: Slow Call Detection.

`@snitchbot.watch_slow` is a decorator that automatically sends an alert
when a function takes longer than the threshold.

Works with both sync and async functions. Zero code changes inside the
function — just add the decorator.

Expected Telegram output:
    🟠 slow call · slow-demo · ...
    __main__.fetch_user_profile took 250 ms (threshold 100 ms)
    Details
        time     ...
        pid      ...
        is_async  true
        location  .../examples/features/watch_slow.py:33

"""
import asyncio
import time

import snitchbot


@snitchbot.watch_slow(threshold_ms=100)
async def fetch_user_profile(user_id: int) -> dict:
    """This function is slow — takes 250ms, threshold is 100ms."""
    print(f"  Fetching profile for user {user_id}...")
    await asyncio.sleep(0.25)
    return {"name": "Alice", "balance": 150.0}


@snitchbot.watch_slow(threshold_ms=500)
def generate_report() -> str:
    """Sync function — also works with watch_slow."""
    print("  Generating report...")
    time.sleep(0.6)  # 600ms > 500ms threshold
    return "report-data"


async def main():
    snitchbot.init("slow-demo", live_dashboard=False)

    # Async slow call
    profile = await fetch_user_profile(42)
    print(f"  Got profile: {profile}")

    await asyncio.sleep(2)

    # Sync slow call
    report = generate_report()
    print(f"  Got report: {report}")

    await asyncio.sleep(3)
    print("Done. Check Telegram for 2 slow call alerts.")


if __name__ == "__main__":
    asyncio.run(main())
