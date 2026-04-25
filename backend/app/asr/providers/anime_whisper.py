from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...model_manager import resolve_model_name
from ..base import ASRProvider
from ..exceptions import PipelineError
from ..helpers import estimate_audio_duration, resolve_provider_model_reference

logger = logging.getLogger(__name__)

_DTYPE_ALIASES = {
    "fp16": "float16",
    "half": "float16",
    "float16": "float16",
    "bf16": "bfloat16",
    "bfloat16": "bfloat16",
    "fp32": "float32",
    "float32": "float32",
    "float": "float32",
    "auto": "auto",
}


def _resolve_torch_dtype(torch: Any, value: Any, device: str) -> tuple[Any, str]:
    requested = str(value or "auto").strip().lower()
    if not requested or requested == "auto":
        return (torch.float16, "float16") if device == "cuda" else (torch.float32, "float32")
    dtype_name = _DTYPE_ALIASES.get(requested)
    if dtype_name is None:
        raise PipelineError(f"anime-whisper dtype 不支持: {value!r}，可用 auto/float32/float16/bfloat16")
    return getattr(torch, dtype_name), dtype_name


class AnimeWhisperProvider(ASRProvider):
    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config, "anime-whisper")
        self.enhance_dialogue = bool(self.advanced.get("anime_whisper_enhance_dialogue", True))
        self.dtype_setting = self.advanced.get("anime_whisper_dtype", "auto")
        self._pipeline: Any | None = None
        self._loaded_name: str | None = None
        self._loaded_device: str | None = None
        self._loaded_dtype_name: str | None = None

    def supports_model(self, model_name: str) -> bool:
        return resolve_model_name(model_name, "anime-whisper").startswith("anime-whisper-")

    def _get_pipeline(self) -> Any:
        try:
            import torch  # type: ignore
            from transformers import pipeline as transformers_pipeline  # type: ignore
        except ImportError as exc:
            raise PipelineError("transformers 未安装，无法执行 Anime-Whisper 识别") from exc
        torch_dtype, dtype_name = _resolve_torch_dtype(torch, self.dtype_setting, self.device)
        if (
            self._pipeline is not None
            and self._loaded_name == self.model_name
            and self._loaded_device == self.device
            and self._loaded_dtype_name == dtype_name
        ):
            return self._pipeline
        model_reference = resolve_provider_model_reference(self.model_name, self.provider_name)
        logger.info(
            "加载 Anime-Whisper 模型: %s, device=%s, torch_dtype=%s",
            model_reference,
            self.device,
            dtype_name,
        )
        pipeline_kwargs: dict[str, Any] = {
            "task": "automatic-speech-recognition",
            "model": model_reference,
            "torch_dtype": torch_dtype,
        }
        if self.device == "cuda":
            pipeline_kwargs["device"] = 0
        self._pipeline = transformers_pipeline(**pipeline_kwargs)
        self._loaded_name = self.model_name
        self._loaded_device = self.device
        self._loaded_dtype_name = dtype_name
        logger.info("Anime-Whisper 模型加载完成: %s", model_reference)
        return self._pipeline

    def transcribe(self, audio_path: Path, language: str | None) -> dict[str, Any]:
        pipe = self._get_pipeline()
        result = pipe(
            str(audio_path),
            generate_kwargs={"language": language or "ja", "num_beams": self.beam_size},
            return_timestamps=True,
        )
        chunks = result.get("chunks") if isinstance(result, dict) else None
        if not isinstance(chunks, list) or not chunks:
            text = str(result.get("text", "") if isinstance(result, dict) else result).strip()
            duration = estimate_audio_duration(audio_path)
            chunks = [{"timestamp": (0.0, duration), "text": text}]
        segments: list[dict[str, Any]] = []
        for chunk in chunks:
            start, end = chunk.get("timestamp", (0.0, 0.0))
            segments.append(
                {
                    "start": float(start or 0.0),
                    "end": float(end or start or 0.0),
                    "text": str(chunk.get("text", "")).strip(),
                }
            )
        return {"segments": segments, "language": str(language or "ja")}
