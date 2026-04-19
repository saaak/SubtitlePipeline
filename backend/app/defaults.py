from __future__ import annotations

import logging
from copy import deepcopy
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def detect_device() -> str:
    """Auto-detect the best available device (cuda or cpu)."""
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            logger.info("检测到 CUDA 设备: %s，使用 GPU 加速", name)
            return "cuda"
    except ImportError:
        pass
    logger.info("未检测到 CUDA，使用 CPU 模式")
    return "cpu"


DEFAULT_CONFIG = {
    "file": {
        "input_dir": "/data",
        "output_to_source_dir": True,
        "allowed_extensions": [".mp4", ".mkv", ".mov", ".avi"],
        "scan_interval_seconds": 5,
        "min_size_mb": 128,
        "max_size_mb": 8192,
    },
    "processing": {
        "max_retries": 1,
        "retry_mode": "restart",
        "keep_intermediates": False,
        "poll_interval_seconds": 2,
        "work_dir": "/config/work",
    },
    "whisper": {
        "provider": "whisperx",
        "model_name": "whisperx-small",
        "device": "auto",
        "audio_format": "wav",
        "sample_rate": 16000,
        # 通用配置（提升到顶层）
        "beam_size": 5,
        "vad_filter": True,
        "vad_threshold": 0.5,
        # 对齐 Provider 选择
        "align_provider": "auto",  # auto | whisperx | qwen-forced | none
        # 高级配置（Provider 特定）
        "advanced": {
            "whisperx_align_extend": 2,
            "faster_whisper_word_timestamps": False,
            "anime_whisper_enhance_dialogue": True,
            "qwen_temperature": 0.0,
        },
    },
    "translation": {
        "enabled": True,
        "target_languages": ["zh"],
        "max_retries": 2,
        "timeout_seconds": 30,
        "api_base_url": "https://api.openai.com",
        "api_key": "",
        "model": "gpt-4o-mini",
        "content_type": "general",
        "custom_prompt": "",
    },
    "subtitle": {
        "bilingual": True,
        "bilingual_mode": "merge",
        "filename_template": "{stem}.forced.{lang}.srt",
        "source_language": "auto",
    },
    "mux": {
        "enabled": False,
        "filename_template": "{stem}.subbed.mkv",
    },
    "logging": {
        "level": "INFO",
    },
}

SYSTEM_LEVEL_FIELDS = {
    ("whisper", "model_name"),
}

RESULT_AFFECTING_GROUPS = {"file", "processing", "whisper", "translation", "subtitle", "mux"}
STAGE_SEQUENCE = [
    "extract_audio",
    "run_asr",
    "align_segments",
    "text_process",
    "translate",
    "subtitle_render",
    "output_finalize",
    "mux",
]


def copy_default_config() -> dict:
    return deepcopy(DEFAULT_CONFIG)
