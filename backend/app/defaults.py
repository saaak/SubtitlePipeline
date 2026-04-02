from __future__ import annotations

from copy import deepcopy

DEFAULT_CONFIG = {
    "file": {
        "input_dir": "/data",
        "output_dir": "/output",
        "allowed_extensions": [".mp4", ".mkv", ".mov", ".avi"],
        "scan_interval_seconds": 5,
        "min_size_mb": 1,
        "max_size_mb": 4096,
        "in_place": False,
    },
    "processing": {
        "backend_mode": "mock",
        "max_retries": 1,
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
        "provider": "mock",
        "target_languages": ["zh-CN"],
        "max_retries": 2,
        "timeout_seconds": 30,
        "mock_prefix_template": "[{lang}] ",
        "fail_languages": [],
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
    "logging": {
        "page_size": 50,
        "level": "INFO",
    },
}

SYSTEM_LEVEL_FIELDS = {
    ("whisper", "model_name"),
    ("whisper", "device"),
    ("whisper", "align_model"),
    ("translation", "provider"),
    ("processing", "backend_mode"),
}

RESULT_AFFECTING_GROUPS = {"file", "processing", "whisper", "translation", "subtitle"}
STAGE_SEQUENCE = [
    "extract_audio",
    "asr",
    "text_process",
    "translate",
    "subtitle_render",
    "output_finalize",
]


def copy_default_config() -> dict:
    return deepcopy(DEFAULT_CONFIG)
