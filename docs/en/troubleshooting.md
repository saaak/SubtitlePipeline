---
layout: default
title: Troubleshooting
nav_order: 5
lang: en
ref: troubleshooting
alt_path: ../zh/troubleshooting.md
---

# Troubleshooting

{% include lang-switch.html %}

## Service Does Not Start

### `docker compose up -d` exits or the container restarts repeatedly

- Check container logs with `docker compose logs -f`.
- Verify that port `8000` is available.
- Confirm the mounted `./config`, `./data`, `./models`, and `./output` directories exist and are writable.

## GPU Deployment Problems

### GPU compose file starts but ASR still runs on CPU

- Make sure you started `docker-compose.gpu.yml` instead of the default compose file.
- Verify Docker GPU runtime support with `gpus: all` on the service.
- Confirm the host driver stack is compatible with CUDA 12.6.

### GPU container fails because `python` is missing

- The GPU image uses `python3` explicitly.
- If you customize Supervisor or shell commands in the container, call `python3` instead of `python`.

## Models Cannot Be Downloaded

### Model downloads stall or fail

- Check outbound network access from the container.
- Configure `HTTP_PROXY`, `HTTPS_PROXY`, or `HF_ENDPOINT` when you need a proxy or mirror.
- Persist the `/models` mount so interrupted downloads can be resumed or retried cleanly.

## No Tasks Appear

### Videos in the library are not detected

- Confirm `file.input_dir` points at the mounted `/data` path inside the container.
- Verify file extensions are listed in `file.allowed_extensions`.
- Check that files are within `min_size_mb` and `max_size_mb` limits.
- Wait at least one `scan_interval_seconds` cycle after updating settings.

## Task Fails During Processing

### Translation errors or rate limits

- Test the translation settings from the UI before running large jobs.
- Verify `translation.api_base_url`, `translation.api_key`, and `translation.model`.
- Increase confidence by keeping `translation.timeout_seconds` and `translation.max_retries` reasonable for your provider.

### Resume does not work as expected

- Set `processing.retry_mode` to `resume` if you want checkpoint-based retries.
- Keep `/config` mounted so the database and work directory survive container restarts.
- Enable `processing.keep_intermediates` temporarily if you need to inspect work files.

## Subtitle Output Issues

### Subtitles are written to the wrong location

- When `file.output_to_source_dir` is `true`, subtitles are written beside the source video.
- When it is `false`, subtitles are written under `/output`.
- Recheck the mount paths if the observed output location does not match the configuration.

### Media server does not detect subtitles

- Use a filename template your media server understands.
- Keep subtitle files in the same directory as the source media when possible.
- Trigger a library refresh in Jellyfin, Emby, or Plex if automatic detection is delayed.

## Related Docs

- [Installation](installation.md)
- [Configuration Reference](configuration.md)
- [Media Server Integration](media-servers.md)
- [FAQ](faq.md)
