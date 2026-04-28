---
layout: default
title: 常见问题
nav_order: 6
lang: zh
ref: faq
alt_path: ../en/faq.md
---

# 常见问题

{% include lang-switch.html %}

## SubtitlePipeline 需要依赖云服务吗？

不需要。ASR 使用你本地安装的模型运行；翻译是可选功能，只有在启用时才需要外部 API。

## 我应该先选哪个 ASR Provider？

建议先从 `whisperx` 和 `whisperx-small` 开始，作为质量和速度的均衡默认值。`faster-whisper` 适合快速预览，`anime-whisper` 适合日语动漫内容，`qwen` 适合更广泛的多语言场景。

## 生成的字幕保存在哪里？

默认情况下，由于 `file.output_to_source_dir` 为 `true`，字幕会直接写到源视频旁边。如果关闭这个选项，字幕会输出到 `/output`。

## 我可以保留中间文件用于排查吗？

可以。启用 `processing.keep_intermediates` 后，任务中间文件会保留在 `processing.work_dir` 中。

## 怎么让 Jellyfin、Emby 或 Plex 自动识别字幕？

把同一套媒体库挂载到 `/data`，保持 `file.output_to_source_dir` 为启用状态，并使用类似 `{stem}.{lang}.srt` 这种兼容的 `subtitle.filename_template`。

## 我需要单独构建这个文档站吗？

不需要。`docs/` 目录已经按 GitHub Pages 原生 Jekyll 渲染方式组织。

## 详细文档有英文版吗？

有。你可以使用页面顶部的切换控件，或直接打开 [English homepage](../en/index.md)。

## 相关文档

- [安装指南](installation.md)
- [配置参考](configuration.md)
- [媒体服务器集成](media-servers.md)
- [故障排查](troubleshooting.md)
