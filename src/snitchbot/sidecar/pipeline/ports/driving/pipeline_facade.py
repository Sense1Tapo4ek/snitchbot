"""Pipeline facade — driving port for the pipeline bounded context."""
from dataclasses import dataclass

from snitchbot.sidecar.pipeline.app.workflows.dispatch_loop_workflow import DispatchLoopWorkflow
from snitchbot.sidecar.pipeline.app.workflows.edit_flusher_workflow import EditFlusherWorkflow
from snitchbot.sidecar.pipeline.domain.central_queue_agg import CentralQueue, QueueItem
from snitchbot.sidecar.pipeline.domain.dedup_cache_agg import DedupCache
from snitchbot.sidecar.pipeline.domain.rate_bucket_vo import RateBucket

__all__ = ["PipelineFacade", "PipelineSnapshot"]


@dataclass(frozen=True, slots=True, kw_only=True)
class PipelineSnapshot:
    """Immutable snapshot of pipeline state for observability."""

    queue_size: int
    dedup_entry_count: int
    rate_bucket_tokens: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PipelineFacade:
    """Driving port for the pipeline context.

    Exposes enqueue, dispatch tick, edit flusher tick, and snapshot.
    """

    _queue: CentralQueue
    _dedup_cache: DedupCache
    _rate_bucket: RateBucket
    _dispatch: DispatchLoopWorkflow
    _edit_flusher: EditFlusherWorkflow

    def enqueue(self, item: QueueItem) -> bool:
        """Enqueue a QueueItem. Returns True if accepted, False if dropped."""
        return self._queue.enqueue(item)

    async def dispatch_tick(self) -> None:
        """Process one item from the queue."""
        await self._dispatch.tick()

    def edit_flusher_tick(self, *, now: float) -> list[dict]:
        """Scan dedup cache for pending edits and return them."""
        return self._edit_flusher.tick(now=now)

    def snapshot(self) -> PipelineSnapshot:
        """Return an immutable snapshot of current pipeline state."""
        return PipelineSnapshot(
            queue_size=len(self._queue),
            dedup_entry_count=len(self._dedup_cache),
            rate_bucket_tokens=self._rate_bucket.tokens,
        )
