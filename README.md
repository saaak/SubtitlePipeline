# SubPipeline

SubPipeline 是一个本地字幕流水线 MVP，提供以下能力：

- FastAPI API Server，提供健康检查、任务、配置、日志接口
- Scanner 目录轮询扫描、稳定性检测、去重入队
- Worker 单任务串行执行 mock 或真实后端字幕流水线
- React SPA，提供任务列表、任务详情、配置管理、日志分页
- Supervisor 单容器多进程启动，支持 `/data`、`/output`、`/models`、`/config` 标准挂载

## 本地开发

### 后端

```bash
cd backend
pip install -r requirements.txt
python -m app.api_server
```

### Scanner

```bash
cd backend
python -m app.scanner_process
```

### Worker

```bash
cd backend
python -m app.worker_process
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

## Docker

### CPU 默认镜像

```bash
docker build -f container/Dockerfile -t subpipeline:cpu .
docker run -p 8000:8000 \
  -v ${PWD}/data:/data \
  -v ${PWD}/output:/output \
  -v ${PWD}/models:/models \
  -v ${PWD}/config:/config \
  subpipeline:cpu
```

### CPU 默认 Compose

```bash
docker compose up --build -d
docker compose logs -f
docker compose down
```

### GPU 可选镜像

```bash
docker build -f container/Dockerfile.gpu -t subpipeline:gpu .
docker run --gpus all -p 8000:8000 \
  -v ${PWD}/data:/data \
  -v ${PWD}/output:/output \
  -v ${PWD}/models:/models \
  -v ${PWD}/config:/config \
  subpipeline:gpu
```

### GPU 可选 Compose

```bash
docker compose -f docker-compose.gpu.yml up --build -d
docker compose -f docker-compose.gpu.yml logs -f
docker compose -f docker-compose.gpu.yml down
```
