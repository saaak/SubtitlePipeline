---
layout: default
title: 故障排查
nav_order: 5
lang: zh
ref: troubleshooting
alt_path: ../en/troubleshooting.md
---

# 故障排查

{% include lang-switch.html %}

## 服务无法启动

### `docker compose up -d` 退出或容器不断重启

- 使用 `docker compose logs -f` 检查容器日志。
- 确认端口 `8000` 没有被占用。
- 确认挂载的 `./config`、`./data`、`./models`、`./output` 目录存在且可写。

## GPU 部署问题

### 使用 GPU compose 文件启动后，ASR 仍然跑在 CPU 上

- 确认你启动的是 `docker-compose.gpu.yml`，而不是默认 compose 文件。
- 确认服务配置中保留了 `gpus: all`。
- 确认宿主机驱动栈兼容 CUDA 12.6。

### GPU 容器报错找不到 `python`

- GPU 镜像中显式使用的是 `python3`。
- 如果你自定义了 Supervisor 配置或脚本，请使用 `python3` 而不是 `python`。

## 模型无法下载

### 模型下载卡住或失败

- 检查容器是否具备外网访问能力。
- 在需要代理或镜像时配置 `HTTP_PROXY`、`HTTPS_PROXY` 或 `HF_ENDPOINT`。
- 持久化 `/models` 挂载目录，方便重试和复用已下载内容。

## 没有出现任务

### 媒体库中的视频没有被检测到

- 确认 `file.input_dir` 指向容器内实际挂载的 `/data` 路径。
- 确认文件扩展名包含在 `file.allowed_extensions` 中。
- 检查文件大小是否位于 `min_size_mb` 与 `max_size_mb` 范围内。
- 更新设置后，至少等待一个 `scan_interval_seconds` 周期。

## 处理任务失败

### 翻译报错或触发限流

- 在批量运行前，先通过 UI 测试翻译配置。
- 检查 `translation.api_base_url`、`translation.api_key` 和 `translation.model`。
- 结合你的翻译服务，合理设置 `translation.timeout_seconds` 与 `translation.max_retries`。

### Resume 没有按预期工作

- 如果你希望基于断点重试，请将 `processing.retry_mode` 设为 `resume`。
- 确保 `/config` 被持久化挂载，这样数据库和工作目录才能在容器重启后保留。
- 如果你需要排查中间产物，可临时启用 `processing.keep_intermediates`。

## 字幕输出问题

### 字幕输出到了错误位置

- 当 `file.output_to_source_dir` 为 `true` 时，字幕会写到源视频旁边。
- 当它为 `false` 时，字幕会写到 `/output`。
- 如果观察到的输出位置与配置不一致，请重新检查挂载路径。

### 媒体服务器没有识别到字幕

- 使用媒体服务器支持的文件名模板。
- 尽量让字幕文件和源媒体放在同一目录。
- 如果自动识别有延迟，可以在 Jellyfin、Emby、Plex 中手动刷新媒体库。

## 相关文档

- [安装指南](installation.md)
- [配置参考](configuration.md)
- [媒体服务器集成](media-servers.md)
- [常见问题](faq.md)
