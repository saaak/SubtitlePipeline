from __future__ import annotations

from pathlib import Path
from typing import Any

from ..cache import WhisperModelCache
from ..exceptions import PipelineError
from ..helpers import normalize_asr_segments


class WhisperXAligner:
    def __init__(self, model_cache: WhisperModelCache | None = None) -> None:
        self.model_cache = model_cache or WhisperModelCache()

    def align(
        self,
        segments: list[dict[str, Any]],
        audio_path: Path,
        language: str | None,
        device: str,
    ) -> list[dict[str, Any]]:
        if not segments:
            return []
        try:
            import whisperx  # type: ignore
        except ImportError as exc:
            raise PipelineError("whisperx 未安装，无法执行强制对齐") from exc

        align_language = str(language or "en").strip() or "en"
        align_model, metadata = self.model_cache.get_align_model(align_language, device)
        aligned = whisperx.align(segments, align_model, metadata, str(audio_path), device)
        return normalize_asr_segments(aligned.get("segments", []))
