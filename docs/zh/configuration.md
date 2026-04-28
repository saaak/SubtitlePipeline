---
layout: default
title: 配置
nav_order: 3
lang: zh
ref: configuration
alt_path: ../en/configuration.md
---

# 配置参考

{% include lang-switch.html %}

SubtitlePipeline 会将配置存储在 SQLite 中，并通过 Web UI 与 `/api/config` 接口暴露。当前主要运行时配置组包括 `file`、`whisper`、`translation`、`subtitle`、`mux` 和 `processing`。

## 文件扫描

| 选项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `input_dir` | string | `/data` | 扫描视频文件的根目录。 |
| `output_to_source_dir` | boolean | `true` | 将字幕写到源视频同目录，而不是备用输出目录。 |
| `allowed_extensions` | string[] | `[.mp4, .mkv, .mov, .avi]` | 扫描器接受的文件扩展名列表。 |
| `scan_interval_seconds` | integer | `5` | 两次目录扫描之间的间隔。 |
| `min_size_mb` | integer | `128` | 扫描器接受的最小文件大小。 |
| `max_size_mb` | integer | `8192` | 扫描器接受的最大文件大小。 |

## Whisper

| 选项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `provider` | string | `whisperx` | 当前激活的 ASR Provider，可选 `whisperx`、`faster-whisper`、`anime-whisper`、`qwen`。 |
| `model_name` | string | `whisperx-small` | 当前模型名称，使用带 Provider 前缀的命名避免冲突。 |
| `device` | string | `auto` | 运行设备选择，后端会自动检测 CUDA，否则回退到 CPU。 |
| `audio_format` | string | `wav` | 转录前临时音频文件格式。 |
| `sample_rate` | integer | `16000` | ASR 预处理时的重采样频率。 |
| `beam_size` | integer | `5` | 支持该参数的 Provider 使用的 Beam Search 宽度。 |
| `vad_filter` | boolean | `true` | 在支持的 Provider 上启用语音活动检测。 |
| `vad_threshold` | number | `0.5` | VAD 灵敏度阈值。 |
| `align_provider` | string | `auto` | 对齐策略，可选 `auto`、`whisperx`、`qwen-forced`、`none`。 |

### Whisper 高级参数

| 选项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `advanced.whisperx_align_extend` | integer | `2` | WhisperX 强制对齐时额外扩展的音频秒数。 |
| `advanced.whisperx_compute_type` | string | `auto` | WhisperX 模型加载时的计算类型。 |
| `advanced.faster_whisper_word_timestamps` | boolean | `false` | 是否在 Faster-Whisper 中启用词级时间戳。 |
| `advanced.faster_whisper_compute_type` | string | `auto` | Faster-Whisper 推理计算类型。 |
| `advanced.anime_whisper_enhance_dialogue` | boolean | `true` | 对 Anime-Whisper 启用对白增强。 |
| `advanced.anime_whisper_dtype` | string | `auto` | Anime-Whisper 的运行 dtype。 |
| `advanced.qwen_temperature` | number | `0.0` | Qwen-ASR 的采样温度。 |
| `advanced.qwen_dtype` | string | `auto` | Qwen-ASR 的运行 dtype。 |
| `advanced.qwen_max_inference_batch_size` | integer | `32` | Qwen-ASR 的最大推理批次大小。 |
| `advanced.qwen_max_new_tokens` | integer | `256` | Qwen-ASR 解码时允许生成的最大 Token 数。 |

### Provider 说明

| Provider | 适用场景 | 默认模型示例 |
| --- | --- | --- |
| `whisperx` | 质量均衡并追求精确时间戳 | `whisperx-small`, `whisperx-medium` |
| `faster-whisper` | 启动更快，适合轻量预览和批处理 | `faster-whisper-small`, `faster-whisper-large-v3` |
| `anime-whisper` | 日语动漫和情绪化对白 | `anime-whisper` |
| `qwen` | 多语言音频和更广的语言覆盖 | `qwen3-asr-0.6b`, `qwen3-asr-1.7b` |

## Translation

| 选项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enabled` | boolean | `true` | 是否在转录后启用翻译。 |
| `target_languages` | string[] | `[zh]` | 输出语言代码，默认是简体中文字幕。 |
| `max_retries` | integer | `2` | 翻译 API 失败时的重试次数。 |
| `timeout_seconds` | integer | `30` | 翻译 API 请求超时时间。 |
| `api_base_url` | string | `https://api.openai.com` | OpenAI 兼容翻译接口的基础地址。 |
| `api_key` | string | `""` | 翻译服务 API Key。 |
| `model` | string | `gpt-4o-mini` | 翻译模型标识。 |
| `content_type` | string | `general` | 用来调整翻译风格和术语的内容预设。 |
| `custom_prompt` | string | `""` | 自定义翻译提示词，填写后会覆盖所选预设。 |

### 翻译内容类型

内置预设包括：`general`、`movie`、`documentary`、`anime`、`tech_talk`、`variety_show`、`news`。

## 字幕输出

| 选项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `bilingual` | boolean | `true` | 在启用翻译时输出双语字幕。 |
| `bilingual_mode` | string | `merge` | 双语布局方式，可选 `merge`、`separate`。 |
| `filename_template` | string | `{stem}.forced.{lang}.srt` | 生成字幕文件名的模板，常用变量有 `{stem}` 和 `{lang}`。 |
| `source_language` | string | `auto` | 传入 ASR 阶段的源语言提示。 |

## Mux

| 选项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `enabled` | boolean | `false` | 是否在字幕生成后将其封装进视频容器。 |
| `filename_template` | string | `{stem}.subbed.mkv` | 封装后视频文件名模板。 |

## Processing

| 选项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `max_retries` | integer | `1` | 失败任务的最大重试次数。 |
| `retry_mode` | string | `restart` | 重试策略，可选 `restart`、`resume`。 |
| `keep_intermediates` | boolean | `false` | 启用后保留任务的中间工作文件。 |
| `poll_interval_seconds` | integer | `2` | Worker 轮询待处理任务的时间间隔。 |
| `work_dir` | string | `/config/work` | 存放任务中间产物与断点数据的基础目录。 |

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SUBPIPELINE_DB_PATH` | `/config/subpipeline.db` | SQLite 数据库路径。 |
| `SUBPIPELINE_MODELS_DIR` | `/models` | 下载模型的根目录。 |
| `SUBPIPELINE_OUTPUT_DIR` | `/output` | 备用字幕输出目录。 |
| `SUBPIPELINE_BROWSE_ROOTS` | `/data,/output,/config` | 目录浏览器允许访问的根路径。 |
| `SUBPIPELINE_FRONTEND_DIST` | `<repo>/frontend/dist` | API 进程提供的前端构建输出目录。 |
| `SUBPIPELINE_HOST` | `0.0.0.0` | API 服务绑定地址。 |
| `SUBPIPELINE_PORT` | `8000` | API 服务端口。 |
| `HTTP_PROXY` / `HTTPS_PROXY` | unset | 外部下载与 API 调用时可选代理。 |
| `HF_ENDPOINT` | unset | 可选 HuggingFace 镜像地址。 |

## 相关文档

- [安装指南](installation.md)
- [媒体服务器集成](media-servers.md)
- [故障排查](troubleshooting.md)
- [常见问题](faq.md)
