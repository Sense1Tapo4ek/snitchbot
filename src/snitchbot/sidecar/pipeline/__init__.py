"""Pipeline bounded context — dedup, rate-limit, dispatch, rendering."""
from .ports.driving.pipeline_facade import PipelineFacade, PipelineSnapshot

__all__ = ["PipelineFacade", "PipelineSnapshot"]
