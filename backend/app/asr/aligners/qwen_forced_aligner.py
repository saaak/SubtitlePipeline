from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..exceptions import PipelineError
from ..helpers import get_models_root
from ..providers.qwen import normalize_qwen_language, timestamps_to_segments

_CJK_CHAR = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def _join_segment_texts(segments: list[dict[str, Any]]) -> str:
    parts = [str(segment.get("text", "")).strip() for segment in segments if str(segment.get("text", "")).strip()]
    if not parts:
        return ""
    merged = parts[0]
    for part in parts[1:]:
        if _CJK_CHAR.search(merged[-1]) or _CJK_CHAR.match(part):
            merged += part
        else:
            merged += f" {part}"
    return merged


class QwenForcedAligner:
    _model: Any | None = None
    _model_reference: str | None = None
    _model_device: str | None = None

    def __init__(self, models_root: Path | None = None) -> None:
        self.models_root = models_root or get_models_root()

    def _resolve_model_reference(self) -> str:
        local_path = self.models_root / "qwen3-forced-aligner"
        if local_path.exists() and any(local_path.iterdir()):
            return str(local_path)
        raise PipelineError("未找到 qwen3-forced-aligner 模型，请先前往模型管理页下载")

    def _get_model(self, device: str) -> Any:
        model_reference = self._resolve_model_reference()
        if (
            self.__class__._model is not None
            and self.__class__._model_reference == model_reference
            and self.__class__._model_device == device
        ):
            return self.__class__._model
        try:
            import torch  # type: ignore
            from qwen_asr import Qwen3ForcedAligner  # type: ignore
        except ImportError as exc:
            raise PipelineError("qwen-asr 未安装，无法执行 Qwen 强制对齐") from exc

        model_kwargs: dict[str, Any] = {
            "dtype": torch.bfloat16 if device == "cuda" else torch.float32,
            "device_map": "cuda:0" if device == "cuda" else "cpu",
        }
        self.__class__._model = Qwen3ForcedAligner.from_pretrained(model_reference, **model_kwargs)
        self.__class__._model_reference = model_reference
        self.__class__._model_device = device
        return self.__class__._model

    def align(
        self,
        segments: list[dict[str, Any]],
        audio_path: Path,
        language: str | None,
        device: str,
    ) -> list[dict[str, Any]]:
        text = _join_segment_texts(segments)
        if not text:
            return []
        qwen_language = normalize_qwen_language(language)
        if not qwen_language:
            raise PipelineError(f"Qwen3-ForcedAligner 不支持语言: {language or 'auto'}")
        model = self._get_model(device)
        results = model.align(audio=str(audio_path), text=text, language=qwen_language)
        aligned_items = results[0] if results else []
        normalized = timestamps_to_segments(aligned_items)
        if not normalized:
            raise PipelineError("Qwen3-ForcedAligner 未返回有效对齐结果")
        return normalized
