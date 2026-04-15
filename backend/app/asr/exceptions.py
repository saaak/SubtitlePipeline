from __future__ import annotations

# Reuse the canonical PipelineError type from app.pipeline so callers can
# consistently catch `PipelineError` regardless of whether the error comes from
# ASR, translation, mux, etc.
from ..pipeline import PipelineError  # noqa: E402

__all__ = ["PipelineError"]
