"""Shared generics: cross-layer error hierarchy and other framework-free helpers."""

from .errors import AdapterError, AppError, DomainError, LayerError, PortError

__all__ = [
    "AdapterError",
    "AppError",
    "DomainError",
    "LayerError",
    "PortError",
]
