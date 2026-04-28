---
layout: default
title: 媒体服务器
nav_order: 4
lang: zh
ref: media-servers
alt_path: ../en/media-servers.md
---

# 媒体服务器集成

{% include lang-switch.html %}

当 SubtitlePipeline 能扫描你的媒体库并把字幕写到媒体服务器已经识别的目录时，效果最好。

## 通用建议

- 将媒体库挂载到 `/data`，让扫描器可以发现视频文件。
- 如果希望字幕直接写到原视频旁边，请保持 `file.output_to_source_dir` 为 `true`。
- 选择符合媒体服务器命名规则的 `subtitle.filename_template`。
- 只有在你更偏好 MKV 成品而不是外挂 `.srt` 时，才启用 `mux.enabled`。

## Jellyfin

Jellyfin 很适合同目录的外挂字幕文件。

推荐配置：

| 配置项 | 值 |
| --- | --- |
| `file.output_to_source_dir` | `true` |
| `subtitle.filename_template` | `{stem}.{lang}.srt` |
| 可选强制字幕模板 | `{stem}.forced.{lang}.srt` |

挂载建议：

- 将 Jellyfin 的媒体库路径挂载到 SubtitlePipeline 的 `/data`。
- 让 SubtitlePipeline 直接把字幕写到源文件旁边，方便 Jellyfin 自然重新扫描。

## Emby

Emby 同样会识别位于源媒体文件旁边的外挂字幕。

推荐配置：

| 配置项 | 值 |
| --- | --- |
| `file.output_to_source_dir` | `true` |
| `subtitle.filename_template` | `{stem}.{lang}.srt` |

挂载建议：

- 让 `/data` 指向 Emby 正在读取的同一套媒体目录。
- 保持文件名和目录结构稳定，避免 Emby 因路径变化而无法发现新字幕。

## Plex

Plex 支持外挂字幕，也常与语言后缀命名方式一起使用。

推荐配置：

| 配置项 | 值 |
| --- | --- |
| `file.output_to_source_dir` | `true` |
| `subtitle.filename_template` | `{stem}.{lang}.srt` |
| 可选 Plex 风格模板 | `{stem}.chinese.srt` |

挂载建议：

- 将 Plex 媒体库挂载到 `/data`。
- 使用符合你当前 Plex 库习惯和字幕代理策略的文件名模板。

## 模板示例

| 模板 | 输出示例 | 说明 |
| --- | --- | --- |
| `{stem}.{lang}.srt` | `Movie.zh.srt` | 最通用的跨服务器命名方式。 |
| `{stem}.forced.{lang}.srt` | `Movie.forced.zh.srt` | 适合强制字幕工作流。 |
| `{stem}.chinese.srt` | `Movie.chinese.srt` | 某些 Plex 环境更偏好的命名方式。 |

## 何时使用备用输出目录

只有在你无法写入源媒体目录时，才把 `file.output_to_source_dir` 设置为 `false`。此时 SubtitlePipeline 会把字幕写到 `/output`，但媒体服务器通常不会自动识别，除非你后续再同步这些文件。

## 相关文档

- [安装指南](installation.md)
- [配置参考](configuration.md)
- [故障排查](troubleshooting.md)
- [常见问题](faq.md)
