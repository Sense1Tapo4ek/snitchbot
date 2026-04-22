"""Lifecycle demo: Multi-Worker (Pre-Fork Model).

Demonstrates snitchbot in a gunicorn-style pre-fork setup where a master
process spawns several worker child processes. Each process connects to the
shared sidecar independently and gets its own lifecycle tracking.

    1. Master calls snitchbot.init("multi-demo", role="master") -> startup event.
    2. Three worker processes are spawned; each calls snitchbot.init with
       role="worker" -> three startup events.
    3. After 3 s the master kills one worker with SIGKILL -> goodbye protocol
       fires for that worker -> `killed` event.
    4. After 2 more seconds the remaining two workers exit cleanly -> two
       `clean_exit` events.
    5. Master exits cleanly -> final `clean_exit` event.

Expected Telegram output (order of startup events may vary):

    ▶ multi-demo (master) started
    ━━━━━━━━━━━━━━━━━━
    pid        1131606
    time       2026-04-17 08:54:13 UTC
    ▶ multi-demo (worker) started
    ━━━━━━━━━━━━━━━━━━
    pid        1131614
    time       2026-04-17 08:54:13 UTC
    ▶ multi-demo (worker) started
    ━━━━━━━━━━━━━━━━━━
    pid        1131615
    time       2026-04-17 08:54:13 UTC
    ▶ multi-demo (worker) started
    ━━━━━━━━━━━━━━━━━━
    pid        1131616
    time       2026-04-17 08:54:13 UTC


    ■ multi-demo (worker) stopped
    ━━━━━━━━━━━━━━━━━━
    pid        1131615
    reason     sigterm
    time       2026-04-17 08:54:18 UTC
    ■ multi-demo (worker) stopped
    ━━━━━━━━━━━━━━━━━━
    pid        1131616
    reason     sigterm
    time       2026-04-17 08:54:18 UTC
    ■ multi-demo (master) stopped
    ━━━━━━━━━━━━━━━━━━
    pid        1131606
    reason     clean_exit
    time       2026-04-17 08:54:18 UTC
    ⚠ multi-demo (worker) killed
    ━━━━━━━━━━━━━━━━━━
    pid        1131614
    reason     killed
    time       2026-04-17 08:54:28 UTC
"""

import multiprocessing
import os
import signal
import time

import snitchbot


def worker_main(worker_id: int) -> None:
    """Entry point for each child worker process."""
    snitchbot.init("multi-demo", role="worker", live_dashboard=False)
    print(f"[worker-{worker_id}] pid={os.getpid()} running")
    # Workers run until killed or parent signals them to stop.
    time.sleep(10.0)
    print(f"[worker-{worker_id}] exiting cleanly")


def main() -> None:
    snitchbot.init("multi-demo", role="master", live_dashboard=False)
    print(f"[master] pid={os.getpid()} started")

    workers: list[multiprocessing.Process] = []
    for i in range(3):
        p = multiprocessing.Process(target=worker_main, args=(i,), daemon=False)
        p.start()
        workers.append(p)

    # Let all workers register with the sidecar.
    time.sleep(3.0)

    # Kill the first worker — mimics a runaway worker being reaped by the master.
    victim = workers[0]
    print(f"[master] killing worker-0 (pid={victim.pid}) with SIGKILL")
    os.kill(victim.pid, signal.SIGKILL)
    victim.join()

    # Give the goodbye protocol time to detect the dead PID.
    time.sleep(2.0)

    # Signal remaining workers to exit cleanly via SIGTERM.
    for i, p in enumerate(workers[1:], start=1):
        print(f"[master] sending SIGTERM to worker-{i} (pid={p.pid})")
        os.kill(p.pid, signal.SIGTERM)

    for p in workers[1:]:
        p.join()

    print("[master] all workers done, master exiting cleanly")


if __name__ == "__main__":
    # 'spawn' start method avoids inheriting the snitchbot client state from
    # the master — each worker starts fresh, matching gunicorn's behavior.
    multiprocessing.set_start_method("spawn")
    main()
