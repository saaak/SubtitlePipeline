---
layout: default
title: Configuration
nav_order: 3
lang: en
ref: configuration
alt_path: ../zh/configuration.md
---

# Configuration Reference

{% include lang-switch.html %}

SubtitlePipeline stores configuration in SQLite and exposes it through the web UI and `/api/config` endpoints. The main runtime groups are `file`, `whisper`, `translation`, `subtitle`, `mux`, and `processing`.

## File

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `input_dir` | string | `/data` | Root directory scanned for video files. |
| `output_to_source_dir` | boolean | `true` | Writes generated subtitles next to the source video instead of the fallback output directory. |
| `allowed_extensions` | string[] | `[.mp4, .mkv, .mov, .avi]` | File extensions accepted by the scanner. |
| `scan_interval_seconds` | integer | `5` | Delay between directory scans. |
| `min_size_mb` | integer | `128` | Minimum file size accepted by the scanner. |
| `max_size_mb` | integer | `8192` | Maximum file size accepted by the scanner. |

## Whisper

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `provider` | string | `whisperx` | Active ASR provider. Supported values are `whisperx`, `faster-whisper`, `anime-whisper`, and `qwen`. |
| `model_name` | string | `whisperx-small` | Active model name. Provider-prefixed names avoid collisions between model families. |
| `device` | string | `auto` | Runtime device selection. The backend auto-detects CUDA and falls back to CPU. |
| `audio_format` | string | `wav` | Temporary audio format used for transcription input. |
| `sample_rate` | integer | `16000` | Audio resample rate for ASR preparation. |
| `beam_size` | integer | `5` | Beam search width used by providers that support it. |
| `vad_filter` | boolean | `true` | Enables voice activity detection where supported. |
| `vad_threshold` | number | `0.5` | VAD sensitivity threshold. |
| `align_provider` | string | `auto` | Alignment strategy. Supported values: `auto`, `whisperx`, `qwen-forced`, `none`. |

### Whisper Advanced

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `advanced.whisperx_align_extend` | integer | `2` | Extra seconds of audio context for WhisperX forced alignment. |
| `advanced.whisperx_compute_type` | string | `auto` | Compute type for WhisperX model loading. |
| `advanced.faster_whisper_word_timestamps` | boolean | `false` | Enables word-level timestamps in Faster-Whisper. |
| `advanced.faster_whisper_compute_type` | string | `auto` | Compute type for Faster-Whisper inference. |
| `advanced.anime_whisper_enhance_dialogue` | boolean | `true` | Applies dialogue-oriented enhancements for Anime-Whisper. |
| `advanced.anime_whisper_dtype` | string | `auto` | Runtime dtype for Anime-Whisper. |
| `advanced.qwen_temperature` | number | `0.0` | Sampling temperature for Qwen-ASR. |
| `advanced.qwen_dtype` | string | `auto` | Runtime dtype for Qwen-ASR. |
| `advanced.qwen_max_inference_batch_size` | integer | `32` | Maximum inference batch size for Qwen-ASR. |
| `advanced.qwen_max_new_tokens` | integer | `256` | Maximum generated tokens for Qwen-ASR decoding. |

### Provider Notes

| Provider | Best For | Default Model Examples |
| --- | --- | --- |
| `whisperx` | Balanced quality and precise timestamps | `whisperx-small`, `whisperx-medium` |
| `faster-whisper` | Faster startup and lightweight preview workflows | `faster-whisper-small`, `faster-whisper-large-v3` |
| `anime-whisper` | Japanese anime and expressive dialogue | `anime-whisper` |
| `qwen` | Multilingual audio and wider language coverage | `qwen3-asr-0.6b`, `qwen3-asr-1.7b` |

## Translation

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | `true` | Enables translation after transcription. |
| `target_languages` | string[] | `[zh]` | Output language codes. The default targets Simplified Chinese subtitles. |
| `max_retries` | integer | `2` | Retry attempts for translation API failures. |
| `timeout_seconds` | integer | `30` | Timeout for translation API requests. |
| `api_base_url` | string | `https://api.openai.com` | Base URL for an OpenAI-compatible translation endpoint. |
| `api_key` | string | `""` | API key for the translation provider. |
| `model` | string | `gpt-4o-mini` | Translation model identifier. |
| `content_type` | string | `general` | Translation preset used to shape subtitle tone and terminology. |
| `custom_prompt` | string | `""` | Optional custom translation prompt that overrides the selected preset. |

### Translation Content Types

Supported built-in presets: `general`, `movie`, `documentary`, `anime`, `tech_talk`, `variety_show`, `news`.

## Subtitle

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `bilingual` | boolean | `true` | Outputs bilingual subtitles when translation is enabled. |
| `bilingual_mode` | string | `merge` | Controls bilingual layout. Supported values: `merge`, `separate`. |
| `filename_template` | string | `{stem}.forced.{lang}.srt` | Template for generated subtitle filenames. Common variables are `{stem}` and `{lang}`. |
| `source_language` | string | `auto` | Source language hint passed into the ASR stage. |

## Mux

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | `false` | Enables subtitle muxing into a video container after subtitle generation. |
| `filename_template` | string | `{stem}.subbed.mkv` | Output filename template for muxed video files. |

## Processing

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `max_retries` | integer | `1` | Maximum retry attempts for a failed task. |
| `retry_mode` | string | `restart` | Retry strategy. Supported values: `restart`, `resume`. |
| `keep_intermediates` | boolean | `false` | Keeps intermediate work files after task completion when enabled. |
| `poll_interval_seconds` | integer | `2` | Worker polling interval for queued tasks. |
| `work_dir` | string | `/config/work` | Base directory used to store task intermediates and resume checkpoints. |

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `SUBPIPELINE_DB_PATH` | `/config/subpipeline.db` | SQLite database path. |
| `SUBPIPELINE_MODELS_DIR` | `/models` | Root directory for downloaded models. |
| `SUBPIPELINE_OUTPUT_DIR` | `/output` | Fallback subtitle output directory. |
| `SUBPIPELINE_BROWSE_ROOTS` | `/data,/output,/config` | Allowed roots for the directory browser. |
| `SUBPIPELINE_FRONTEND_DIST` | `<repo>/frontend/dist` | Frontend build output served by the API process. |
| `SUBPIPELINE_HOST` | `0.0.0.0` | API server bind host. |
| `SUBPIPELINE_PORT` | `8000` | API server port. |
| `HTTP_PROXY` / `HTTPS_PROXY` | unset | Optional outbound proxy for downloads and API traffic. |
| `HF_ENDPOINT` | unset | Optional HuggingFace mirror endpoint. |

## Related Docs

- [Installation](installation.md)
- [Media Server Integration](media-servers.md)
- [Troubleshooting](troubleshooting.md)
- [FAQ](faq.md)
