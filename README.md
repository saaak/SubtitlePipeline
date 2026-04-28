# SubtitlePipeline

Self-hosted subtitle generation for media libraries. SubtitlePipeline scans videos, runs local ASR, optionally translates text, and writes ready-to-use subtitles for Jellyfin, Emby, and Plex.

[Full documentation](docs/en/index.md) | [Chinese README](README_zh.md)

## Core Features

- Automatic subtitle generation pipeline for video libraries.
- Multiple ASR providers: WhisperX, Faster-Whisper, Anime-Whisper, and Qwen-ASR.
- Optional OpenAI-compatible translation with preset-aware prompts.
- Subtitle output beside source files for media server pickup.
- Optional MKV muxing with FFmpeg.
- Web UI for setup, task monitoring, models, and settings.

## Quick Start

```bash
docker compose up -d
```

Open [http://localhost:8000](http://localhost:8000) and complete the setup wizard.
