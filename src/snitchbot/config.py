"""Unified snitchbot configuration — single source for client and sidecar.

All env vars use the SNITCHBOT_ prefix. Reads from environment + .env file.

Client-side fields: token, chat_id, service, disabled.
Sidecar-side fields: sidecar_socket, sidecar_service, sidecar_log, tz, debug.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # --- Sidecar-side (set by spawner at runtime) ---
    sidecar_socket: str = ""
    sidecar_service: str = ""
    sidecar_log: str | None = None
    tz: str | None = None
    debug: bool = False
    live_dashboard: bool = True
    sample_interval_sec: int = 5
    chart_width: int = 35

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
