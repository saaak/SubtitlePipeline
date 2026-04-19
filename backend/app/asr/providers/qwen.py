from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ...model_manager import resolve_model_name
from ..base import ASRProvider
from ..exceptions import PipelineError
from ..helpers import estimate_audio_duration, resolve_provider_model_reference

logger = logging.getLogger(__name__)

# Qwen ASR requires full language names instead of ISO codes
_ISO_TO_QWEN_LANGUAGE: dict[str, str] = {
    "zh": "Chinese",
    "zh-cn": "Chinese",
    "zh-tw": "Chinese",
    "en": "English",
    "yue": "Cantonese",
    "ar": "Arabic",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "id": "Indonesian",
    "it": "Italian",
    "ko": "Korean",
    "ru": "Russian",
    "th": "Thai",
    "vi": "Vietnamese",
    "ja": "Japanese",
    "tr": "Turkish",
    "hi": "Hindi",
    "ms": "Malay",
    "nl": "Dutch",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "pl": "Polish",
    "cs": "Czech",
    "fil": "Filipino",
    "tl": "Filipino",
    "fa": "Persian",
    "el": "Greek",
    "ro": "Romanian",
    "hu": "Hungarian",
    "mk": "Macedonian",
}

_QWEN_SUPPORTED = frozenset(_ISO_TO_QWEN_LANGUAGE.values())

# Split on sentence-ending punctuation or long silence gaps
_SENTENCE_END = re.compile(r"[。！？…!?]+$")
_MAX_GAP_SECONDS = 1.5


def timestamps_to_segments(time_stamps: list[Any]) -> list[dict[str, Any]]:
    """Convert word-level Qwen time_stamps to sentence-level segments.

    The Qwen API returns word-level timestamps (ts.start_time / ts.end_time / ts.text).
    This function groups them into sentence segments by punctuation boundaries and
    silence gaps, which is what the subtitle pipeline expects.
    """
    if not time_stamps:
        return []

    segments: list[dict[str, Any]] = []
    buffer: list[dict[str, Any]] = []  # {"text", "end"}
    seg_start: float | None = None

    for ts in time_stamps:
        word = str(getattr(ts, "text", "")).strip()
        if not word:
            continue
        start = float(getattr(ts, "start_time", 0.0))
        end = float(getattr(ts, "end_time", 0.0))

        # Flush on long silence gap between this word and the previous
        if buffer and (start - buffer[-1]["end"]) > _MAX_GAP_SECONDS:
            text = "".join(w["text"] for w in buffer).strip()
            if text:
                segments.append({"start": seg_start, "end": buffer[-1]["end"], "text": text})
            buffer = []
            seg_start = None

        if seg_start is None:
            seg_start = start
        buffer.append({"text": word, "end": end})

        # Flush on sentence-ending punctuation
        if _SENTENCE_END.search(word):
            text = "".join(w["text"] for w in buffer).strip()
            if text:
                segments.append({"start": seg_start, "end": end, "text": text})
            buffer = []
            seg_start = None

    # Flush any remaining words
    if buffer and seg_start is not None:
        text = "".join(w["text"] for w in buffer).strip()
        if text:
            segments.append({"start": seg_start, "end": buffer[-1]["end"], "text": text})

    return segments


def normalize_qwen_language(language: str | None) -> str | None:
    """Convert ISO language code to Qwen ASR full language name."""
    if language is None:
        return None
    # Already a full name
    if language in _QWEN_SUPPORTED:
        return language
    mapped = _ISO_TO_QWEN_LANGUAGE.get(language.lower())
    if mapped:
        return mapped
    logger.warning("Qwen ASR: 未知语言代码 %r，将作为自动检测处理", language)
    return None


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
        qwen_language = normalize_qwen_language(language)
        logger.info("开始 Qwen ASR 转录: %s，语言: %s", audio_path, qwen_language or "auto")
        results = model.transcribe(audio=str(audio_path), language=qwen_language, return_time_stamps=True)

        if not results or len(results) == 0:
            duration = estimate_audio_duration(audio_path)
            return {"segments": [{"start": 0.0, "end": duration, "text": ""}], "language": language or "auto"}

        result = results[0]
        detected_language = result.language if hasattr(result, "language") else (language or "auto")
        text = str(result.text) if hasattr(result, "text") else ""
        logger.info("Qwen ASR 转录完成，语言: %s，文本长度: %d", detected_language, len(text))

        time_stamps = getattr(result, "time_stamps", None)
        if time_stamps:
            segments = timestamps_to_segments(time_stamps)
            if segments:
                return {"segments": segments, "language": detected_language}

        # Fallback: no timestamps — return full text as a single timed segment
        duration = estimate_audio_duration(audio_path)
        return {
            "segments": [{"start": 0.0, "end": duration, "text": text}],
            "language": detected_language,
        }


_timestamps_to_segments = timestamps_to_segments
_normalize_language = normalize_qwen_language
