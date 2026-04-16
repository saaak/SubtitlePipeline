from __future__ import annotations

from pathlib import Path
from typing import Any

from ...model_manager import resolve_model_name
from ..base import ASRProvider
from ..exceptions import PipelineError
from ..helpers import resolve_provider_model_reference


class FasterWhisperProvider(ASRProvider):
    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config, "faster-whisper")
        self.word_timestamps = bool(self.advanced.get("faster_whisper_word_timestamps", False))
        self._model: Any | None = None
        self._loaded_name: str | None = None
        self._loaded_device: str | None = None

    def supports_model(self, model_name: str) -> bool:
        return resolve_model_name(model_name, "faster-whisper").startswith("faster-whisper-")

    def _get_model(self) -> Any:
        if self._model is not None and self._loaded_name == self.model_name and self._loaded_device == self.device:
            return self._model
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as exc:
            raise PipelineError("faster-whisper 未安装，无法执行识别") from exc
        compute_type = "float16" if self.device == "cuda" else "int8"
        model_reference = resolve_provider_model_reference(self.model_name, self.provider_name)
        self._model = WhisperModel(model_reference, device=self.device, compute_type=compute_type)
        self._loaded_name = self.model_name
        self._loaded_device = self.device
        return self._model

    def transcribe(self, audio_path: Path, language: str | None) -> dict[str, Any]:
        model = self._get_model()
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            vad_parameters={"threshold": self.vad_threshold},
            word_timestamps=self.word_timestamps,
        )
        normalized = [
            {
                "start": float(segment.start),
                "end": float(segment.end),
                "text": str(segment.text).strip(),
            }
            for segment in segments
        ]
        detected_language = getattr(info, "language", language or "auto")
        return {"segments": normalized, "language": str(detected_language)}
