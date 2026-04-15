from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...model_manager import resolve_model_name
from ..base import ASRProvider
from ..exceptions import PipelineError
from ..helpers import estimate_audio_duration, resolve_provider_model_reference

logger = logging.getLogger(__name__)


class QwenASRProvider(ASRProvider):
    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config, "qwen")
        self.temperature = float(self.advanced.get("qwen_temperature", 0.0))
        self._model: Any | None = None
        self._loaded_name: str | None = None

    def supports_model(self, model_name: str) -> bool:
        return resolve_model_name(model_name, "qwen").startswith("qwen")

    def _get_model(self) -> Any:
        if self._model is not None and self._loaded_name == self.model_name:
            return self._model
        try:
            import torch  # type: ignore
            from qwen_asr import Qwen3ASRModel  # type: ignore
        except ImportError as exc:
            raise PipelineError("qwen-asr 未安装，请运行: pip install qwen-asr") from exc

        model_reference = resolve_provider_model_reference(self.model_name, self.provider_name)
        logger.info("加载 Qwen ASR 模型: %s", model_reference)
        model_kwargs: dict[str, Any] = {
            "dtype": torch.bfloat16 if self.device == "cuda" else torch.float32,
            "max_inference_batch_size": 1,
            "max_new_tokens": 2048,
        }
        model_kwargs["device_map"] = "cuda:0" if self.device == "cuda" else "cpu"
        self._model = Qwen3ASRModel.from_pretrained(model_reference, **model_kwargs)
        self._loaded_name = self.model_name
        logger.info("Qwen ASR 模型加载完成")
        return self._model

    def transcribe(self, audio_path: Path, language: str | None) -> dict[str, Any]:
        model = self._get_model()
        logger.info("开始 Qwen ASR 转录: %s", audio_path)
        results = model.transcribe(audio=str(audio_path), language=language)

        if not results or len(results) == 0:
            duration = estimate_audio_duration(audio_path)
            return {"segments": [{"start": 0.0, "end": duration, "text": ""}], "language": language or "auto"}

        result = results[0]
        detected_language = result.language if hasattr(result, "language") else (language or "auto")
        text = result.text if hasattr(result, "text") else ""
        logger.info("Qwen ASR 转录完成，语言: %s", detected_language)

        if hasattr(result, "segments") and result.segments:
            segments = []
            for seg in result.segments:
                segments.append(
                    {
                        "start": float(seg.start if hasattr(seg, "start") else 0.0),
                        "end": float(seg.end if hasattr(seg, "end") else 0.0),
                        "text": str(seg.text if hasattr(seg, "text") else "").strip(),
                    }
                )
            return {"segments": segments, "language": detected_language}

        duration = estimate_audio_duration(audio_path)
        return {
            "segments": [{"start": 0.0, "end": duration, "text": text}],
            "language": detected_language,
        }
