# SubtitlePipeline

**Self-hosted subtitle generation pipeline for your media library — automatically generate Chinese subtitles for every video file and output them alongside the originals, ready for Jellyfin / Emby / Plex to pick up.**

[**中文文档**](README_zh.md)

---

## Features

- **Automatic Subtitle Generation** — Point it at your media directory, and it will automatically scan, recognize speech, translate, and generate `.srt` subtitle files for every video
- **Media Server Integration** — Output subtitles directly to the source video directory with configurable naming (e.g. `Movie.zh.srt`, `Movie.forced.zh.srt`) for automatic pickup by Jellyfin, Emby, Plex, etc.
- **Multi-Provider ASR** — Switch between WhisperX, Faster-Whisper, Anime-Whisper, and Qwen-ASR from the settings page, each with provider-specific tuning options
- **Smart Translation** — OpenAI-compatible API translation with 7 content-type presets (movie, documentary, anime, tech talk, etc.), sliding-window context, and rate-limit handling
- **Subtitle Muxing** — Optionally mux subtitles back into the video container via FFmpeg

## Quick Start

### Docker Compose (Recommended)

**CPU:**

```bash
docker compose up --build -d
```

**GPU (NVIDIA CUDA):**

```bash
docker compose -f docker-compose.gpu.yml up --build -d
```

Open http://localhost:8000 in your browser. The setup wizard will guide you through initial configuration.

### Docker Build

**CPU:**

```bash
docker build -f container/Dockerfile -t subtitlepipeline:cpu .
docker run -p 8000:8000 \
  -v ${PWD}/data:/data \
  -v ${PWD}/output:/output \
  -v ${PWD}/models:/models \
  -v ${PWD}/config:/config \
  subtitlepipeline:cpu
```

**GPU:**

```bash
docker build -f container/Dockerfile.gpu -t subtitlepipeline:gpu .
docker run --gpus all -p 8000:8000 \
  -v ${PWD}/data:/data \
  -v ${PWD}/output:/output \
  -v ${PWD}/models:/models \
  -v ${PWD}/config:/config \
  subtitlepipeline:gpu
```

### Volume Mounts

| Path | Purpose |
|------|---------|
| `/data` | Input video files (your media library) |
| `/output` | Fallback output directory |
| `/models` | ASR model storage for all providers |
| `/config` | SQLite database and config |

## Media Server Integration

SubtitlePipeline is designed to work seamlessly with media servers. By default, generated subtitles are written **alongside the original video files** in the source directory, so media servers can automatically detect and load them.

### Subtitle Filename Template

The `subtitle.filename_template` setting controls the output filename. Available variables:

- `{stem}` — original video filename without extension
- `{lang}` — target language code (e.g. `zh`)

**Examples for different media servers:**

| Template | Output Example | Compatible With |
|----------|---------------|-----------------|
| `{stem}.{lang}.srt` | `Movie.zh.srt` | Jellyfin, Emby, Plex |
| `{stem}.forced.{lang}.srt` | `Movie.forced.zh.srt` | Jellyfin (forced subtitle) |
| `{stem}.chinese.srt` | `Movie.chinese.srt` | Plex |

### Output Modes

| Setting | Behavior |
|---------|----------|
| `file.output_to_source_dir = true` (default) | Subtitles are placed next to the original video — ideal for media servers |
| `file.output_to_source_dir = false` | Subtitles are placed in the `/output` directory |

## Configuration

Configuration is managed through the Web UI settings page and persisted in SQLite.

| Group | Key Settings |
|-------|-------------|
| `file` | input_dir, output_to_source_dir, allowed_extensions, scan_interval |
| `whisper` | provider, model_name, device (auto-detect cuda/cpu), provider_config |
| `translation` | enabled, target_languages, api_base_url, api_key, model, content_type |
| `subtitle` | bilingual, bilingual_mode (merge/separate), filename_template, source_language |
| `mux` | enabled, filename_template |
| `processing` | max_retries, retry_mode (restart/resume) |

### ASR Providers

| Provider | Best For | Notes |
|----------|----------|-------|
| `whisperx` | Accurate subtitle timestamps | Uses forced alignment and provider-prefixed models like `whisperx-small` |
| `faster-whisper` | Fast preview and batch jobs | Faster startup, optional VAD and word timestamps |
| `anime-whisper` | Japanese anime dialogue | Defaults to Japanese and exposes dialogue-oriented options |
| `qwen` | Multilingual mixed-content transcription | Transformer-based audio model with temperature / forced-alignment settings |

### Model Naming

Models now use provider-prefixed names to avoid collisions:

- `whisperx-small`
- `faster-whisper-large-v3`
- `anime-whisper`
- `qwen3-asr-0.6b`
- `qwen3-asr-1.7b`

When activating a model from the model manager, the backend automatically updates both `whisper.model_name` and `whisper.provider`.

### Translation Content Types

Built-in prompt presets for different content types:

`general` · `movie` · `documentary` · `anime` · `tech_talk` · `variety_show` · `news`

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `SUBPIPELINE_DB_PATH` | SQLite database path |
| `SUBPIPELINE_MODELS_DIR` | Model storage directory |
| `SUBPIPELINE_OUTPUT_DIR` | Default output directory |
| `SUBPIPELINE_BROWSE_ROOTS` | Allowed directories for browser |
| `SUBPIPELINE_FRONTEND_DIST` | Frontend dist path |
| `HTTP_PROXY` / `HTTPS_PROXY` | Network proxy |
| `HF_ENDPOINT` | HuggingFace mirror endpoint |

## Local Development

### Prerequisites

- Python 3.12+
- Node.js 22+
- FFmpeg
- Optional ASR extras are included in `backend/requirements.txt`: `whisperx`, `faster-whisper`, `transformers`, `librosa`

### Backend

```bash
cd backend
pip install -r requirements.txt

# Start API server
python -m app.api_server

# Start scanner
python -m app.scanner_process

# Start worker
python -m app.worker_process
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, Pydantic, SQLite (WAL) |
| ASR Engine | WhisperX, Faster-Whisper, Anime-Whisper, Qwen-ASR |
| Translation | OpenAI-compatible API (httpx + openai SDK) |
| Audio/Video | FFmpeg |
| Frontend | React 18, TypeScript, React Router 6, Vite 5 |
| Deployment | Docker, Supervisor, Docker Compose |
| GPU Support | NVIDIA CUDA 12.6, PyTorch 2.8 |

## License

MIT
