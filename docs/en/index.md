---
layout: default
title: Home
nav_order: 1
lang: en
ref: index
alt_path: ../zh/index.md
---

# SubtitlePipeline Documentation

{% include lang-switch.html %}

SubtitlePipeline is a self-hosted subtitle generation pipeline for media libraries. It scans videos, runs ASR with multiple providers, optionally translates text, and writes `.srt` subtitles next to your media files for Jellyfin, Emby, and Plex.

## Start Here

- [Installation](installation.md) - Deploy with Docker on CPU or NVIDIA GPU, configure volumes, and enable GitHub Pages.
- [Configuration Reference](configuration.md) - Full reference for all runtime configuration groups and defaults.
- [Media Server Integration](media-servers.md) - Naming patterns and mount strategies for Jellyfin, Emby, and Plex.
- [Troubleshooting](troubleshooting.md) - Common deployment, model, translation, and subtitle output issues.
- [FAQ](faq.md) - Quick answers for day-to-day usage questions.

## Core Features

- Self-hosted subtitle pipeline with a web UI and background scanner/worker services.
- Multiple ASR providers: WhisperX, Faster-Whisper, Anime-Whisper, and Qwen-ASR.
- Optional OpenAI-compatible translation with content presets and custom prompts.
- Output subtitles beside source videos or into a fallback output directory.
- Optional subtitle muxing back into MKV containers with FFmpeg.
- Designed for media server workflows and GitHub Pages-friendly documentation.

## Recommended Reading Path

1. Follow the [installation guide](installation.md) to deploy the service.
2. Review the [configuration reference](configuration.md) before changing defaults.
3. Apply the [media server guide](media-servers.md) for your library layout.
4. Use [troubleshooting](troubleshooting.md) and [FAQ](faq.md) when something behaves unexpectedly.
