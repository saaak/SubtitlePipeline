# SubtitlePipeline

面向媒体库的自托管字幕生成工具。SubtitlePipeline 会扫描视频、执行本地语音识别、按需翻译文本，并为 Jellyfin、Emby、Plex 输出可直接使用的字幕文件。

[完整文档](docs/zh/index.md) | [English README](README.md)

## 核心特性

- 面向视频媒体库的自动字幕生成流水线。
- 支持 WhisperX、Faster-Whisper、Anime-Whisper、Qwen-ASR 多种 ASR Provider。
- 支持兼容 OpenAI 的可选翻译与内容类型预设。
- 可将字幕直接输出到源视频目录，方便媒体服务器自动识别。
- 支持使用 FFmpeg 进行可选的 MKV 字幕封装。
- 提供 Web UI 用于初始化、任务管理、模型管理和设置。

## 快速开始

```bash
docker compose up -d
```

启动后访问 [http://localhost:8000](http://localhost:8000)，按引导完成初始化配置。
