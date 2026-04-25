from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...model_manager import resolve_model_name
from ..base import ASRProvider
from ..exceptions import PipelineError
from ..helpers import resolve_provider_model_reference

logger = logging.getLogger(__name__)

_COMPUTE_TYPE_ALIASES = {
    "fp16": "float16",
    "half": "float16",
    "float16": "float16",
    "bf16": "bfloat16",
    "bfloat16": "bfloat16",
    "fp32": "float32",
    "float32": "float32",
    "int8": "int8",
    "int8_float32": "int8_float32",
    "int8-float32": "int8_float32",
    "int8_fp32": "int8_float32",
    "int8-fp32": "int8_float32",
    "int8_float16": "int8_float16",
    "int8-float16": "int8_float16",
    "int8_fp16": "int8_float16",
    "int8-fp16": "int8_float16",
    "int8_bfloat16": "int8_bfloat16",
    "int8-bfloat16": "int8_bfloat16",
    "int8_bf16": "int8_bfloat16",
    "int8-bf16": "int8_bfloat16",
    "int16": "int16",
    "auto": "auto",
    "default": "default",
}


def _resolve_compute_type(value: Any, device: str) -> str:
    requested = str(value or "auto").strip().lower()
    if not requested or requested == "auto":
        return "float16" if device == "cuda" else "int8"
    compute_type = _COMPUTE_TYPE_ALIASES.get(requested)
    if compute_type is None:
        raise PipelineError(
            "faster-whisper compute_type 不支持: "
            f"{value!r}，可用 auto/default/float32/float16/bfloat16/int8/int8_float16/int8_float32/int8_bfloat16/int16"
        )
    return compute_type


class FasterWhisperProvider(ASRProvider):
    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config, "faster-whisper")
        self.word_timestamps = bool(self.advanced.get("faster_whisper_word_timestamps", False))
        self.compute_type = _resolve_compute_type(self.advanced.get("faster_whisper_compute_type", "auto"), self.device)
        self._model: Any | None = None
        self._loaded_name: str | None = None
        self._loaded_device: str | None = None
        self._loaded_compute_type: str | None = None

    def supports_model(self, model_name: str) -> bool:
        return resolve_model_name(model_name, "faster-whisper").startswith("faster-whisper-")

    def _get_model(self) -> Any:
        if (
            self._model is not None
            and self._loaded_name == self.model_name
            and self._loaded_device == self.device
            and self._loaded_compute_type == self.compute_type
        ):
            return self._model
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as exc:
            raise PipelineError("faster-whisper 未安装，无法执行识别") from exc
        model_reference = resolve_provider_model_reference(self.model_name, self.provider_name)
        logger.info(
            "加载 Faster-Whisper 模型: %s, device=%s, compute_type=%s",
            model_reference,
            self.device,
            self.compute_type,
        )
        self._model = WhisperModel(model_reference, device=self.device, compute_type=self.compute_type)
        self._loaded_name = self.model_name
        self._loaded_device = self.device
        self._loaded_compute_type = self.compute_type
        logger.info("Faster-Whisper 模型加载完成: %s", model_reference)
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
