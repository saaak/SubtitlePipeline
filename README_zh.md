# SubtitlePipeline

**本地自托管字幕生成流水线 —— 自动为媒体库中的每个视频生成中文字幕，输出到视频同目录，Jellyfin / Emby / Plex 等流媒体服务器即可自动挂载。**

[**English**](README.md)

---

## 功能特性

- **自动生成字幕** — 指定媒体目录，自动扫描视频文件、识别语音、翻译并生成 `.srt` 字幕文件
- **流媒体服务器集成** — 字幕直接输出到视频同目录，支持自定义命名规则（如 `影片.zh.srt`、`影片.forced.zh.srt`），Jellyfin / Emby / Plex 自动识别加载
- **多 Provider 语音识别** — 可在设置页切换 WhisperX、Faster-Whisper、Anime-Whisper、Qwen-ASR，并分别配置专属参数
- **智能翻译** — 兼容 OpenAI API 的翻译服务，内置 7 种内容类型预设（电影、纪录片、动漫、技术演讲等），支持滑动窗口上下文和速率限制处理
- **字幕封装** — 可选通过 FFmpeg 将字幕封装回视频容器

## 快速开始

### Docker Compose（推荐）

使用 Docker Hub 预构建镜像，无需本地编译：

**CPU 版本：**

```bash
docker compose up -d
```

**GPU 版本（NVIDIA CUDA）：**

```bash
docker compose -f docker-compose.gpu.yml up -d
```

打开浏览器访问 http://localhost:8000，引导设置向导将帮助你完成初始配置。

### 本地构建镜像（可选）

如果需要自定义修改或离线部署，可以本地构建镜像：

**CPU 版本：**

```bash
# 构建镜像
docker build -f container/Dockerfile -t subtitlepipeline:cpu .

# 使用本地镜像启动（修改 docker-compose.yml 中的 image 字段为 subtitlepipeline:cpu）
docker compose up -d
```

**GPU 版本：**

```bash
# 构建镜像
docker build -f container/Dockerfile.gpu -t subtitlepipeline:gpu .

# 使用本地镜像启动（修改 docker-compose.gpu.yml 中的 image 字段为 subtitlepipeline:gpu）
docker compose -f docker-compose.gpu.yml up -d
```

### 挂载目录

| 路径 | 用途 |
|------|------|
| `/data` | 输入视频文件（你的媒体库目录） |
| `/output` | 备用输出目录 |
| `/models` | 所有 ASR Provider 的模型存储 |
| `/config` | SQLite 数据库和配置 |

## 流媒体服务器集成

SubtitlePipeline 专为配合流媒体服务器使用而设计。默认情况下，生成的字幕会**直接写入视频源文件所在目录**，流媒体服务器可以自动检测并加载。

### 字幕文件名模板

`subtitle.filename_template` 配置项控制输出文件名。可用变量：

- `{stem}` — 原始视频文件名（不含扩展名）
- `{lang}` — 目标语言代码（如 `zh`）

**不同流媒体服务器的推荐配置：**

| 模板 | 输出示例 | 适配服务器 |
|------|---------|-----------|
| `{stem}.{lang}.srt` | `电影.zh.srt` | Jellyfin、Emby、Plex |
| `{stem}.forced.{lang}.srt` | `电影.forced.zh.srt` | Jellyfin（强制字幕） |
| `{stem}.chinese.srt` | `电影.chinese.srt` | Plex |

### 输出模式

| 配置项 | 行为 |
|--------|------|
| `file.output_to_source_dir = true`（默认） | 字幕输出到视频同目录 —— 流媒体服务器的理想选择 |
| `file.output_to_source_dir = false` | 字幕输出到 `/output` 目录 |

## 配置说明

配置通过 Web 管理界面进行管理，持久化存储在 SQLite 中。

| 配置组 | 关键配置项 |
|--------|-----------|
| `file` | 输入目录、输出到源目录、允许的扩展名、扫描间隔 |
| `whisper` | provider、模型名称、设备（自动检测 cuda/cpu）、provider_config |
| `translation` | 启用翻译、目标语言、API 地址、API 密钥、模型、内容类型 |
| `subtitle` | 双语字幕、双语模式（合并/分离）、文件名模板、源语言 |
| `mux` | 启用封装、文件名模板 |
| `processing` | 最大重试次数、重试模式（重启/续传） |

### ASR Provider 选择建议

| Provider | 适用场景 | 说明 |
|----------|----------|------|
| `whisperx` | 需要精准字幕时间戳 | 默认 Provider，模型名形如 `whisperx-small` |
| `faster-whisper` | 快速预览、批量处理 | 启动更快，可配置 VAD 与词级时间戳 |
| `anime-whisper` | 日语动漫对白 | 默认偏向日语，可调对话增强 |
| `qwen` | 多语言混合与复杂语境 | 基于 transformers，可调 temperature / 强制对齐 |

### 模型命名规则

为避免不同 Provider 的模型重名，所有模型使用带前缀的统一命名：

- `whisperx-small`
- `faster-whisper-large-v3`
- `anime-whisper`
- `qwen3-asr-0.6b`
- `qwen3-asr-1.7b`

在模型管理页切换模型时，后端会自动同步更新 `whisper.model_name` 与 `whisper.provider`。

### 翻译内容类型

内置不同内容类型的提示词预设：

`general`（通用）· `movie`（电影）· `documentary`（纪录片）· `anime`（动漫）· `tech_talk`（技术演讲）· `variety_show`（综艺）· `news`（新闻）

### 环境变量

| 变量 | 用途 |
|------|------|
| `SUBPIPELINE_DB_PATH` | SQLite 数据库路径 |
| `SUBPIPELINE_MODELS_DIR` | 模型存储目录 |
| `SUBPIPELINE_OUTPUT_DIR` | 默认输出目录 |
| `SUBPIPELINE_BROWSE_ROOTS` | 目录浏览器允许的根目录 |
| `SUBPIPELINE_FRONTEND_DIST` | 前端构建产物路径 |
| `HTTP_PROXY` / `HTTPS_PROXY` | 网络代理 |
| `HF_ENDPOINT` | HuggingFace 镜像端点 |

## 本地开发

### 前置依赖

- Python 3.12+
- Node.js 22+
- FFmpeg
- `backend/requirements.txt` 已包含可选 ASR 依赖：`whisperx`、`faster-whisper`、`transformers`、`librosa`

### 后端

```bash
cd backend
pip install -r requirements.txt

# 启动 API 服务
python -m app.api_server

# 启动扫描器
python -m app.scanner_process

# 启动工作进程
python -m app.worker_process
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.12、FastAPI、Pydantic、SQLite (WAL) |
| 语音识别 | WhisperX、Faster-Whisper、Anime-Whisper、Qwen-ASR |
| 翻译 | OpenAI 兼容 API (httpx + openai SDK) |
| 音视频 | FFmpeg |
| 前端 | React 18、TypeScript、React Router 6、Vite 5 |
| 部署 | Docker、Supervisor、Docker Compose |
| GPU 支持 | NVIDIA CUDA 12.6、PyTorch 2.8 |

## 许可证

MIT
