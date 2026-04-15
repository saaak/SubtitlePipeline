from __future__ import annotations

from .anime_whisper import AnimeWhisperProvider
from .faster_whisper import FasterWhisperProvider
from .qwen import QwenASRProvider
from .whisperx import WhisperXProvider

__all__ = [
    "AnimeWhisperProvider",
    "FasterWhisperProvider",
    "QwenASRProvider",
    "WhisperXProvider",
]
