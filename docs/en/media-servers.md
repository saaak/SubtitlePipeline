---
layout: default
title: Media Servers
nav_order: 4
lang: en
ref: media-servers
alt_path: ../zh/media-servers.md
---

# Media Server Integration

{% include lang-switch.html %}

SubtitlePipeline works best when it can scan your media library and write subtitle files where your media server already looks for them.

## General Recommendations

- Mount your media library into `/data` so the scanner can discover files.
- Keep `file.output_to_source_dir` set to `true` when you want subtitles written beside the original videos.
- Choose a `subtitle.filename_template` that matches your server's subtitle naming rules.
- Use `mux.enabled` only if you prefer MKV outputs instead of sidecar `.srt` files.

## Jellyfin

Jellyfin works well with standard sidecar subtitle files in the same folder as the source video.

Recommended settings:

| Setting | Value |
| --- | --- |
| `file.output_to_source_dir` | `true` |
| `subtitle.filename_template` | `{stem}.{lang}.srt` |
| Optional forced template | `{stem}.forced.{lang}.srt` |

Mount strategy:

- Mount the Jellyfin media library path into SubtitlePipeline as `/data`.
- Let SubtitlePipeline write subtitles next to the source files so Jellyfin rescans them naturally.

## Emby

Emby also detects sidecar subtitles next to the source media files.

Recommended settings:

| Setting | Value |
| --- | --- |
| `file.output_to_source_dir` | `true` |
| `subtitle.filename_template` | `{stem}.{lang}.srt` |

Mount strategy:

- Point `/data` at the same library tree Emby reads.
- Preserve filenames and directory structure so Emby sees newly generated subtitle files without manual relocation.

## Plex

Plex supports sidecar subtitles and can work with language-based naming conventions.

Recommended settings:

| Setting | Value |
| --- | --- |
| `file.output_to_source_dir` | `true` |
| `subtitle.filename_template` | `{stem}.{lang}.srt` |
| Alternative Plex-friendly template | `{stem}.chinese.srt` |

Mount strategy:

- Mount the Plex media library into `/data`.
- Use a filename template that fits your Plex library conventions and subtitle agent behavior.

## Template Examples

| Template | Example Output | Notes |
| --- | --- | --- |
| `{stem}.{lang}.srt` | `Movie.zh.srt` | Safest cross-server option. |
| `{stem}.forced.{lang}.srt` | `Movie.forced.zh.srt` | Useful for forced subtitle workflows. |
| `{stem}.chinese.srt` | `Movie.chinese.srt` | Alternative naming some Plex setups prefer. |

## When To Use Fallback Output

Set `file.output_to_source_dir` to `false` only when you cannot write into the source library. In that mode SubtitlePipeline writes subtitles into `/output`, but your media server will not pick them up automatically unless you copy or sync the files afterward.

## Related Docs

- [Installation](installation.md)
- [Configuration Reference](configuration.md)
- [Troubleshooting](troubleshooting.md)
- [FAQ](faq.md)
