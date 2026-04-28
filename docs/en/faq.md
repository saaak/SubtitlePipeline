---
layout: default
title: FAQ
nav_order: 6
lang: en
ref: faq
alt_path: ../zh/faq.md
---

# FAQ

{% include lang-switch.html %}

## Does SubtitlePipeline require cloud services?

No. ASR runs locally with your installed models. Translation is optional and only requires an external API if you enable it.

## Which ASR provider should I start with?

Start with `whisperx` and `whisperx-small` for a balanced default. Use `faster-whisper` for faster preview jobs, `anime-whisper` for Japanese anime content, and `qwen` for broader multilingual coverage.

## Where are generated subtitles saved?

By default they are written next to the source video because `file.output_to_source_dir` is `true`. If you disable that option, subtitles go to `/output`.

## Can I keep intermediate files for debugging?

Yes. Enable `processing.keep_intermediates` to keep task work files in `processing.work_dir`.

## How do I make subtitles appear in Jellyfin, Emby, or Plex?

Mount the same media library into `/data`, keep `file.output_to_source_dir` enabled, and use a compatible `subtitle.filename_template` such as `{stem}.{lang}.srt`.

## Do I need to build the documentation site?

No. The `docs/` folder is designed for GitHub Pages native rendering through Jekyll.

## Is there Chinese documentation for the full site?

Yes. Use the switcher at the top of the page or open the [Chinese homepage](../zh/index.md).

## Related Docs

- [Installation](installation.md)
- [Configuration Reference](configuration.md)
- [Media Server Integration](media-servers.md)
- [Troubleshooting](troubleshooting.md)
