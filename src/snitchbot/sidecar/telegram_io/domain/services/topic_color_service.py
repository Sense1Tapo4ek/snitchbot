"""TopicColorService — deterministic colour assignment from a 7-colour palette.

Layer: domain (stdlib only).
"""
import hashlib

TOPIC_COLOR_PALETTE: tuple[int, ...] = (
    7322096, 16766590, 13338331, 9367192, 16749490, 16478047, 7396918,
)


class TopicColorService:
    @staticmethod
    def color_for(service: str, *, override: int | None = None) -> int:
        if override is not None:
            if override not in TOPIC_COLOR_PALETTE:
                raise ValueError(
                    f"override {override!r} not in Telegram palette {TOPIC_COLOR_PALETTE}"
                )
            return override
        digest = hashlib.blake2b(service.encode("utf-8"), digest_size=2).digest()
        idx = int.from_bytes(digest, "big") % len(TOPIC_COLOR_PALETTE)
        return TOPIC_COLOR_PALETTE[idx]
