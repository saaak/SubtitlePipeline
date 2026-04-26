from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..exceptions import PipelineError
from ..helpers import get_models_root
from ..providers.qwen import normalize_qwen_language, timestamps_to_segments

logger = logging.getLogger(__name__)

_ALIGN_MARGIN_SECONDS = 0.35
_MIN_ALIGN_WINDOW_SECONDS = 0.8


def _segment_window(segment: dict[str, Any]) -> tuple[float, float]:
    start = max(float(segment.get("start", 0.0)) - _ALIGN_MARGIN_SECONDS, 0.0)
    end = max(
        float(segment.get("end", segment.get("start", 0.0))) + _ALIGN_MARGIN_SECONDS,
        start + _MIN_ALIGN_WINDOW_SECONDS,
    )
    return start, end


def _offset_segments(segments: list[dict[str, Any]], offset: float) -> list[dict[str, Any]]:
    return [
        {
            "start": max(0.0, float(segment.get("start", 0.0)) + offset),
            "end": max(0.0, float(segment.get("end", 0.0)) + offset),
            "text": str(segment.get("text", "")).strip(),
        }
        for segment in segments
        if str(segment.get("text", "")).strip()
    ]


def _load_audio_slice(audio_path: Path, start: float, end: float) -> tuple[Any, int]:
    try:
        import librosa  # type: ignore
    except ImportError as exc:
        raise PipelineError("缺少 librosa，无法裁剪音频片段进行 Qwen 强制对齐") from exc
    duration = max(end - start, _MIN_ALIGN_WINDOW_SECONDS)
    samples, sample_rate = librosa.load(
        str(audio_path),
        sr=None,
        mono=True,
        offset=start,
        duration=duration,
    )
    if len(samples) == 0:
        raise PipelineError("音频片段为空，无法执行 Qwen 强制对齐")
    return samples, int(sample_rate)


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
        qwen_language = normalize_qwen_language(language)
        if not qwen_language:
            raise PipelineError(f"Qwen3-ForcedAligner 不支持语言: {language or 'auto'}")
        model = self._get_model(device)
        aligned_segments: list[dict[str, Any]] = []
        fallback_count = 0

        for segment in segments:
            text = str(segment.get("text", "")).strip()
            if not text:
                continue
            window_start, window_end = _segment_window(segment)
            try:
                audio_input = _load_audio_slice(audio_path, window_start, window_end)
                results = model.align(audio=audio_input, text=text, language=qwen_language)
                aligned_items = results[0] if results else []
                normalized = timestamps_to_segments(aligned_items)
                if normalized:
                    aligned_segments.extend(_offset_segments(normalized, window_start))
                    continue
            except Exception as exc:
                logger.warning("Qwen 强制对齐失败，回退原始时间戳: %s", exc)

            fallback_count += 1
            fallback_start = max(0.0, float(segment.get("start", window_start)))
            fallback_end = max(fallback_start, float(segment.get("end", window_end)))
            aligned_segments.append(
                {
                    "start": fallback_start,
                    "end": fallback_end,
                    "text": text,
                }
            )

        if not aligned_segments:
            raise PipelineError("Qwen3-ForcedAligner 未返回有效对齐结果")
        if fallback_count:
            logger.warning("Qwen 强制对齐存在 %d 个片段回退到原始时间戳", fallback_count)
        return aligned_segments
