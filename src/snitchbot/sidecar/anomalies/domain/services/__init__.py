"""Anomaly detection domain services — v2 unified 3-mode model.

Pure Python stdlib — no frameworks, no I/O.
"""
from .cpu_service import check_cpu, check_total_cpu
from .cpu_sustained_service import check_cpu_sustained
from .fd_leak_service import check_fd_leak
from .fds_service import check_fds
from .rss_service import check_rss, check_total_rss
from .rss_spike_service import check_rss_spike
from .thread_growth_service import check_thread_growth
from .threads_service import check_threads

# Deprecated alias
check_memory = check_rss

__all__ = [
    "check_rss",
    "check_cpu",
    "check_fds",
    "check_threads",
    "check_total_rss",
    "check_total_cpu",
    "check_memory",
    # Deprecated v1
    "check_rss_spike",
    "check_cpu_sustained",
    "check_fd_leak",
    "check_thread_growth",
]
