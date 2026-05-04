"""Celery integration — initialize snitchbot in every prefork worker.

Usage::

    from celery import Celery
    from snitchbot.integrations.celery import install

    app = Celery("tasks", broker="redis://...")
    install(app, service="my-worker")

What ``install`` does:
    Subscribes to Celery's ``worker_process_init`` signal so every prefork
    worker calls ``snitchbot.init`` once it has been forked from the
    master. Each worker registers as a separate client and appears as its
    own row in the live dashboard.
"""
from typing import Any

import snitchbot

__all__ = ["install"]


def install(celery_app: Any, *, service: str, **init_kwargs: Any) -> None:
    """Initialize snitchbot in every Celery prefork worker after fork.

    ``role`` defaults to ``"worker"``; pass an explicit ``role`` kwarg
    to override (e.g. ``role="beat"`` for a Beat process).
    """
    from celery.signals import worker_process_init

    init_kwargs.setdefault("role", "worker")

    @worker_process_init.connect(weak=False)
    def _on_worker_init(**_kwargs: Any) -> None:
        snitchbot.init(service, **init_kwargs)
