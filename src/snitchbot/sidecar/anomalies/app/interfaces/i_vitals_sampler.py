"""IVitalsSampler — Protocol for vitals sampling.

"""
from typing import Protocol

from snitchbot.shared.domain import ClientState
from snitchbot.shared.domain import VitalsSnapshot

__all__ = ["IVitalsSampler"]

class IVitalsSampler(Protocol):
    """Driving interface for vitals sampling. Implemented by PsutilVitalsSampler."""

    def sample_one_client(self, client: ClientState, *, now: float) -> VitalsSnapshot: ...
    def sample_into_state(self, client: ClientState, *, now: float) -> None: ...
