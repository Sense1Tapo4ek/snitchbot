"""Unified snitchbot configuration — single source for client and sidecar.

All env vars use the SNITCHBOT_ prefix. Reads from environment + .env file.

Client-side fields: token, chat_id, service, disabled, forum, topic_color.
Sidecar-side fields: sidecar_socket, sidecar_service, sidecar_log, tz, debug.
"""
from __future__ import annotations

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from snitchbot.sidecar.telegram_io.domain.services.topic_color_service import (
    TOPIC_COLOR_PALETTE,
)


class SnitchbotConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SNITCHBOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Required (user-facing) ---
    token: str
    chat_id: str

    # --- Client-side ---
    service: str = "default"
    disabled: bool = False

    # --- Forum mode (Invariant F1) ---
    forum: bool | Literal["auto"] = "auto"
    topic_color: int | None = None

    # --- Sidecar-side (set by spawner at runtime) ---
    sidecar_socket: str = ""
    sidecar_service: str = ""
    sidecar_log: str | None = None
    tz: str | None = None
    debug: bool = False
    live_dashboard: bool = True
    sample_interval_sec: int = 5
    chart_width: int = 35

    @field_validator("forum", mode="before")
    @classmethod
    def _validate_forum(cls, v: object) -> object:
        # Already a bool or the literal "auto" — accept as-is.
        if isinstance(v, bool) or v == "auto":
            return v
        # Coerce string env-var values: "true"/"false"/"auto" (case-insensitive).
        if isinstance(v, str):
            lowered = v.strip().lower()
            if lowered == "auto":
                return "auto"
            if lowered in ("true", "1", "yes", "on"):
                return True
            if lowered in ("false", "0", "no", "off"):
                return False
        raise ValueError("forum must be True, False, or 'auto'")

    @field_validator("topic_color")
    @classmethod
    def _validate_topic_color(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v not in TOPIC_COLOR_PALETTE:
            raise ValueError(
                f"topic_color {v!r} not in Telegram palette {TOPIC_COLOR_PALETTE}"
            )
        return v

    # --- Aliases for backward compat with __main__.py field names ---
    @property
    def socket_path(self) -> str:
        return self.sidecar_socket

    @property
    def log_path(self) -> str | None:
        return self.sidecar_log

    @classmethod
    def from_env(cls) -> SnitchbotConfig:
        """Construct from environment variables + .env file."""
        return cls()
