"""ASCII chart renderer — wraps asciichartpy.

Driven port: isolates the external library behind a simple interface.
"""
from __future__ import annotations

import asciichartpy

__all__ = ["AsciichartRenderer"]

_UNIT_MAP = {
    "cpu": "%",
    "mem": "MB",
    "fds": "",
    "threads": "",
}

_LABEL_MAP = {
    "cpu": "CPU",
    "mem": "RSS",
    "fds": "FDs",
    "threads": "Threads",
}


class AsciichartRenderer:
    """Renders metric series as ASCII line charts."""

    def render(
        self,
        series: list[float],
        *,
        height: int = 10,
        metric: str = "",
        window_label: str = "",
    ) -> str:
        """Render a single metric series as an ASCII chart.

        Args:
            series: List of float values (chronological order).
            height: Chart height in rows.
            metric: Metric name for the label (cpu/mem/fds/threads).
            window_label: Human-readable window label (e.g. "5m", "1h").

        Returns:
            Multi-line ASCII chart string. Returns "no data" if series is empty.
        """
        if not series:
            label = _LABEL_MAP.get(metric, metric)
            return f"{label}: no data"

        chart = asciichartpy.plot(series, {"height": height})

        # Build header
        label = _LABEL_MAP.get(metric, metric)
        unit = _UNIT_MAP.get(metric, "")
        current = series[-1]
        min_val = min(series)
        max_val = max(series)

        if unit:
            header = (
                f"{label} ({window_label})"
                f" cur={current:.1f}{unit}"
                f" min={min_val:.1f} max={max_val:.1f}"
            )
        else:
            header = (
                f"{label} ({window_label})"
                f" cur={current:.0f}"
                f" min={min_val:.0f} max={max_val:.0f}"
            )

        return f"{header}\n{chart}"

    def render_multi(
        self,
        metrics: dict[str, list[float]],
        *,
        height: int = 6,
        window_label: str = "",
    ) -> str:
        """Render multiple metrics as stacked mini-charts.

        Args:
            metrics: Dict of metric_name -> series.
            height: Height per chart.
            window_label: Human-readable window label.

        Returns:
            Stacked charts separated by blank lines.
        """
        parts: list[str] = []
        for metric, series in metrics.items():
            parts.append(self.render(
                series, height=height, metric=metric, window_label=window_label,
            ))
        return "\n\n".join(parts)
