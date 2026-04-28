---
layout: default
title: 首页
nav_order: 1
lang: zh
ref: index
alt_path: ../en/index.md
---

# SubtitlePipeline 文档

{% include lang-switch.html %}

SubtitlePipeline 是一个面向媒体库的自托管字幕生成流水线。它可以扫描视频文件、调用多种 ASR Provider 识别语音、按需翻译文本，并将 `.srt` 字幕输出到媒体文件旁，方便 Jellyfin、Emby、Plex 直接加载。

## 从这里开始

- [安装指南](installation.md) - 使用 Docker 在 CPU 或 NVIDIA GPU 环境部署，配置卷挂载，并启用 GitHub Pages。
- [配置参考](configuration.md) - 查看所有运行时配置组及默认值的完整说明。
- [媒体服务器集成](media-servers.md) - 了解 Jellyfin、Emby、Plex 的命名建议与挂载策略。
- [故障排查](troubleshooting.md) - 常见部署、模型、翻译和字幕输出问题的处理办法。
- [常见问题](faq.md) - 日常使用中的高频问题速查。

## 核心特性

- 提供带 Web UI 的自托管字幕流水线，并包含后台扫描与处理服务。
- 支持 WhisperX、Faster-Whisper、Anime-Whisper、Qwen-ASR 多种 ASR Provider。
- 支持兼容 OpenAI 的可选翻译，并提供内容类型预设与自定义提示词。
- 可将字幕输出到源视频旁边，或输出到备用目录。
- 支持通过 FFmpeg 将字幕可选封装回 MKV。
- 基于 GitHub Pages 友好的 Jekyll Markdown 文档结构。

## 推荐阅读路径

1. 先阅读 [安装指南](installation.md) 完成部署。
2. 再查看 [配置参考](configuration.md) 了解默认值和可调项。
3. 如果要接入媒体库，继续阅读 [媒体服务器集成](media-servers.md)。
4. 遇到问题时查看 [故障排查](troubleshooting.md) 和 [常见问题](faq.md)。
