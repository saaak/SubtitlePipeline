---
layout: default
title: 安装
nav_order: 2
lang: zh
ref: installation
alt_path: ../en/installation.md
---

# 安装指南

{% include lang-switch.html %}

最简单的部署方式是使用 Docker Compose。SubtitlePipeline 默认在 `8000` 端口提供 Web UI，并把运行时状态保存到挂载目录中。

## Docker Compose

### CPU 部署

如果你不需要 GPU 加速，直接使用默认 compose 文件：

```bash
docker compose up -d
```

这会启动 API 服务、扫描器和 Worker，它们在同一个容器内由 Supervisor 管理。

### GPU 部署

在 NVIDIA 环境下使用 GPU compose 文件：

```bash
docker compose -f docker-compose.gpu.yml up -d
```

要求：

- 主机具备 NVIDIA GPU 与 Docker GPU Runtime 支持。
- 驱动栈兼容 CUDA 12.6。
- 有足够的显存和磁盘空间用于安装 ASR 模型。

GPU 镜像基于 `nvidia/cuda:12.6.1-runtime-ubuntu22.04`，容器内显式使用 `python3` 运行服务。

## 卷挂载

当前 compose 文件挂载了 4 个目录：

| 容器路径 | 用途 | 说明 |
| --- | --- | --- |
| `/data` | 输入媒体库 | 扫描器会在这里发现视频文件。 |
| `/output` | 备用字幕输出目录 | 当 `file.output_to_source_dir` 为 `false` 时使用。 |
| `/models` | 下载后的 ASR 与对齐模型 | 建议持久化，避免重复下载。 |
| `/config` | SQLite 数据库和运行时配置 | 同时保存工作目录与任务状态。 |

仓库根目录下的示例挂载：

```yaml
volumes:
  - ./data:/data
  - ./output:/output
  - ./models:/models
  - ./config:/config
```

## 环境变量说明

compose 文件中常见的环境变量：

| 变量 | 用途 |
| --- | --- |
| `SUBPIPELINE_PORT` | API 服务对外暴露的 HTTP 端口。 |
| `SUBPIPELINE_DB_PATH` | 容器内 SQLite 数据库路径。 |
| `SUBPIPELINE_FRONTEND_DIST` | 前端静态资源目录。 |
| `HTTP_PROXY` / `HTTPS_PROXY` | 模型下载或外部 API 调用时可选的代理。 |
| `HF_ENDPOINT` | 可选的 HuggingFace 镜像地址。 |

## 首次启动

1. 容器启动后打开 `http://localhost:8000`。
2. 完成初始化向导。
3. 选择一个 ASR Provider，并安装至少一个模型。
4. 设置媒体输入目录与字幕输出方式。
5. 按需配置翻译和封装选项。

## 本地构建镜像

仅在你需要自定义修改或离线部署时本地构建。

### CPU 镜像

```bash
docker build -f container/Dockerfile -t subtitlepipeline:cpu .
```

### GPU 镜像

```bash
docker build -f container/Dockerfile.gpu -t subtitlepipeline:gpu .
```

如果使用本地构建镜像，请先修改 compose 文件中的 `image` 字段，再启动服务。

## GitHub Pages 设置

`docs/` 目录已经兼容 GitHub Pages 原生 Jekyll 渲染。

1. 将仓库推送到 GitHub。
2. 打开仓库的 `Settings`。
3. 进入 `Pages`。
4. 将 `Source` 设置为 `Deploy from a branch`。
5. 选择分支 `main`，目录 `/docs`。
6. 保存并等待站点发布。

启用后，GitHub Pages 会直接渲染这些 Markdown 文件，无需额外构建步骤。

## 相关文档

- [配置参考](configuration.md)
- [媒体服务器集成](media-servers.md)
- [故障排查](troubleshooting.md)
- [常见问题](faq.md)
