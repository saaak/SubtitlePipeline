from __future__ import annotations

from copy import deepcopy

DEFAULT_CONFIG = {
    "file": {
        "input_dir": "/data",
        "output_dir": "",
        "allowed_extensions": [".mp4", ".mkv", ".mov", ".avi"],
        "scan_interval_seconds": 5,
        "min_size_mb": 1,
        "max_size_mb": 4096,
    },
    "processing": {
        "max_retries": 1,
        "retry_mode": "restart",
        "keep_intermediates": False,
        "poll_interval_seconds": 2,
        "work_dir": "/config/work",
    },
    "whisper": {
        "model_name": "small",
        "device": "cpu",
        "audio_format": "wav",
        "sample_rate": 16000,
        "align_model": "auto",
    },
    "translation": {
        "enabled": True,
        "target_languages": ["zh-CN"],
        "max_retries": 2,
        "timeout_seconds": 30,
        "api_base_url": "https://api.openai.com",
        "api_key": "",
        "model": "gpt-4o-mini",
    },
    "subtitle": {
        "bilingual": True,
        "bilingual_mode": "merge",
        "filename_template": "{stem}.{lang}.srt",
        "source_language": "auto",
        "text_process_style": "basic",
    },
    "mux": {
        "enabled": False,
        "output_dir": "",
        "filename_template": "{stem}.subbed.mkv",
    },
    "logging": {
        "page_size": 50,
        "level": "INFO",
    },
}

SYSTEM_LEVEL_FIELDS = {
    ("whisper", "model_name"),
    ("whisper", "device"),
    ("whisper", "align_model"),
}

RESULT_AFFECTING_GROUPS = {"file", "processing", "whisper", "translation", "subtitle", "mux"}
STAGE_SEQUENCE = [
    "extract_audio",
    "asr",
    "text_process",
    "translate",
    "subtitle_render",
    "output_finalize",
    "mux",
]


def copy_default_config() -> dict:
    return deepcopy(DEFAULT_CONFIG)
