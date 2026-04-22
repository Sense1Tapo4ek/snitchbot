"""Feature demo: Live Dashboard.

snitchbot pins a message in your Telegram chat that auto-updates with
real-time vitals: CPU, RSS, threads, FDs, uptime, and connected clients.

By default `live_dashboard=True` (always on). Set `live_dashboard=False`
to disable it.

The dashboard updates every 10 seconds and looks like this:

    🟢 dashboard-demo · live
    ━━━━━━━━━━━━━━━━━━

    Clients (1)
    PID      role        rss      cpu    threads  fds
    123456   standalone  45 MB    2.3%   4        14

    Sidecar
      uptime   0h 5m
      updated  2026-04-17 12:00:00 UTC

    Last 5m
      errors    0
      warnings  1
      slow      0
      anomaly   0

Interactive commands you can try while it's running:
    /status    — full sidecar snapshot
    /chart     — ASCII charts of CPU, memory, FDs, threads
    /export    — download vitals as CSV file
    /test      — send a test notification
"""
import time

import snitchbot


def main():
    # live_dashboard=True is the default — shown here for clarity
    snitchbot.init("dashboard-demo", live_dashboard=True)

    print("Live dashboard is active in Telegram.")
    print("It will auto-update every 10 seconds.")
    print()
    print("Try these commands in Telegram while it's running:")
    print("  /status    — sidecar snapshot")
    print("  /chart     — ASCII vitals charts")
    print("  /export    — download vitals CSV")
    print("  /test      — test notification")
    print()
    print("Running for 2 minutes...")

    # Send a few notifications to make the dashboard counters interesting
    time.sleep(10)
    snitchbot.notify("First warning", severity="warning")
    print("  Sent warning notification.")

    time.sleep(15)
    snitchbot.notify("Second warning", severity="warning")
    print("  Sent another warning.")

    time.sleep(95)
    print("Done.")


if __name__ == "__main__":
    main()
