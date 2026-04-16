from __future__ import annotations

from pathlib import Path
from typing import Any

from ...model_manager import resolve_model_name
from ..base import ASRProvider
from ..cache import WhisperModelCache
from ..exceptions import PipelineError
from ..helpers import normalize_asr_segments


class WhisperXProvider(ASRProvider):
    def __init__(self, config: dict[str, Any], model_cache: WhisperModelCache | None = None) -> None:
        super().__init__(config, "whisperx")
        self.model_cache = model_cache or WhisperModelCache()
        self.align_extend = int(self.advanced.get("whisperx_align_extend", 2))

    def supports_model(self, model_name: str) -> bool:
        return resolve_model_name(model_name, "whisperx").startswith("whisperx-")

    def transcribe(self, audio_path: Path, language: str | None) -> dict[str, Any]:
        try:
            import whisperx  # type: ignore
        except ImportError as exc:
            raise PipelineError("whisperx 未安装，无法执行真实识别") from exc
        model = self.model_cache.get_model(self.model_name, self.device, language)
        result = model.transcribe(str(audio_path))

        should_align = self.align_method in ("auto", "whisperx")
        if not should_align or self.align_method == "none":
            return {
                "segments": normalize_asr_segments(result.get("segments", [])),
                "language": str(result.get("language", language or "auto")),
            }

        align_model, metadata = self.model_cache.get_align_model(str(result.get("language", "en")), self.device)
        aligned = whisperx.align(result["segments"], align_model, metadata, str(audio_path), self.device)
        return {
            "segments": normalize_asr_segments(aligned["segments"]),
            "language": str(result.get("language", language or "auto")),
        }
