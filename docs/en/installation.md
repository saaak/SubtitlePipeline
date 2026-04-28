---
layout: default
title: Installation
nav_order: 2
lang: en
ref: installation
alt_path: ../zh/installation.md
---

# Installation

{% include lang-switch.html %}

Use Docker Compose for the simplest deployment. SubtitlePipeline exposes a web UI on port `8000` and stores runtime state in mounted directories.

## Docker Compose

### CPU Deployment

Use the default compose file when you do not need GPU acceleration:

```bash
docker compose up -d
```

This starts the API server, scanner, and worker in a single container managed by Supervisor.

### GPU Deployment

Use the GPU compose file on NVIDIA systems with compatible drivers:

```bash
docker compose -f docker-compose.gpu.yml up -d
```

Requirements:

- NVIDIA GPU with Docker GPU runtime support.
- CUDA 12.6 compatible driver stack.
- Enough VRAM and disk space for the ASR models you plan to install.

The GPU image is based on `nvidia/cuda:12.6.1-runtime-ubuntu22.04` and runs the service with `python3` inside the container.

## Volume Mounts

The provided compose files mount four directories:

| Container Path | Purpose | Notes |
| --- | --- | --- |
| `/data` | Input media library | Point this at your videos so the scanner can discover files. |
| `/output` | Fallback subtitle output directory | Used when `file.output_to_source_dir` is `false`. |
| `/models` | Downloaded ASR and aligner models | Persist this to avoid repeated downloads. |
| `/config` | SQLite database and runtime configuration | Also stores work directories and task state. |

Example bind mounts from the repository root:

```yaml
volumes:
  - ./data:/data
  - ./output:/output
  - ./models:/models
  - ./config:/config
```

## Environment Notes

Useful environment variables in the compose files:

| Variable | Purpose |
| --- | --- |
| `SUBPIPELINE_PORT` | HTTP port exposed by the API server. |
| `SUBPIPELINE_DB_PATH` | SQLite database file path inside the container. |
| `SUBPIPELINE_FRONTEND_DIST` | Built frontend assets path. |
| `HTTP_PROXY` / `HTTPS_PROXY` | Optional proxy for model downloads and outbound API calls. |
| `HF_ENDPOINT` | Optional HuggingFace mirror endpoint. |

## First Run

1. Open `http://localhost:8000` after the container starts.
2. Complete the setup wizard.
3. Choose an ASR provider and install at least one model.
4. Set your media input directory and preferred subtitle output behavior.
5. Optionally configure translation and mux settings.

## Local Image Build

Build locally only if you need custom modifications or offline deployment.

### CPU Image

```bash
docker build -f container/Dockerfile -t subtitlepipeline:cpu .
```

### GPU Image

```bash
docker build -f container/Dockerfile.gpu -t subtitlepipeline:gpu .
```

If you build locally, update the `image` field in the compose file before starting the stack.

## GitHub Pages Setup

The documentation site in `docs/` is compatible with GitHub Pages native Jekyll rendering.

1. Push the repository to GitHub.
2. Open `Settings` in the repository.
3. Go to `Pages`.
4. Set `Source` to `Deploy from a branch`.
5. Select branch `main` and folder `/docs`.
6. Save and wait for the site to publish.

Once enabled, GitHub Pages renders these Markdown files without any extra build step.

## Related Docs

- [Configuration Reference](configuration.md)
- [Media Server Integration](media-servers.md)
- [Troubleshooting](troubleshooting.md)
- [FAQ](faq.md)
