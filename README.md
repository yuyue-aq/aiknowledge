# 知溯 AiKnowledge MVP

这是一个以 DeepSeek Flash + `BAAI/bge-large-zh-v1.5` 为核心的可信知识工作台 MVP：资料进入私有对象存储，后台解析并生成 1024 维向量，所有者问答保留引用快照，公开访客只能检索分享链接当前开放分类。

## 当前交付范围

- 后端：`aiknowledge/`，FastAPI、SQLAlchemy async、pgvector、Redis/Celery、MinIO。
- 前端：`aiknowledge_frontend/`，Taro 4.2.1 + React + TypeScript，可构建 H5/小程序。
- 模型：DeepSeek `deepseek-flash`（瞬时网络/5xx 错误有限重试）；Embedding `BAAI/bge-large-zh-v1.5`，默认 1024 维，支持批量生成。
- 问答：普通 JSON 与 SSE 增量事件；前端支持 `AbortController` 停止生成、SSE 不可用时降级 JSON；连续追问只使用最近用户问题，不把回答当作事实证据。
- 安全：公开会话/提问进程级限流、可信 Origin 校验、安全响应头、公开响应不包含来源字段。
- 用户登录/注册和真实授权：按你的明确要求暂缓，目录和入口保留；在接入公网前必须先补齐身份认证与 owner scope。

## Windows Docker 启动（推荐）

所有 Docker Compose 命令都从仓库根目录 `D:\develop\aiknowledge` 执行。

1. 启动 Docker Desktop，并确认使用 Linux containers。检查：

   ```powershell
   docker info
   ```

2. 首次准备本地配置（真实密钥只放在未提交的 `.env`）：

   ```powershell
   Copy-Item aiknowledge\.env.example aiknowledge\.env
   # 编辑 aiknowledge\.env，至少设置 AIKNOWLEDGE_DEEPSEEK_API_KEY
   ```

   仓库已有 `models\embedding\bge-large-zh-v1.5`；若重新部署，需要把同名模型目录挂载到 Compose 的 `/models/bge-large-zh-v1.5`。

3. 一次性构建并启动全部运行时容器（Postgres、Redis、MinIO、API、Worker、前端）：

   ```powershell
   docker compose --env-file aiknowledge\.env up -d --build
   docker compose --env-file aiknowledge\.env ps
   ```

   API 容器启动时自动执行 `alembic upgrade head`。访问 `http://localhost:8000/health/live` 检查存活，`http://localhost:8000/health/ready` 检查 Postgres、Redis、MinIO；前端地址为 `http://localhost:10086`。

4. 查看应用日志：

   ```powershell
   docker compose --env-file aiknowledge\.env logs -f api worker frontend
   ```

5. 停止运行时（不会删除 Postgres/MinIO 命名卷）：

   ```powershell
   docker compose --env-file aiknowledge\.env down
   ```

   前端 H5 已在 Nginx 容器内构建并托管，不需要再运行 IDE 中的 `npm run dev:h5` 或本机 Uvicorn。Compose 默认将前端 API 地址编译为 `http://localhost:8000/api/v1`；如果修改了 API 端口，请同步修改 `.env` 中的 `TARO_APP_API_BASE` 和 Compose 端口映射后重新执行 `up -d --build`。跨域地址必须同时加入 `AIKNOWLEDGE_CORS_ALLOWED_ORIGINS`。

## 测试与静态检查

后端要求 Python 3.14（项目 `requires-python`）：

```powershell
cd aiknowledge
$env:UV_CACHE_DIR='D:\develop\aiknowledge\.uv-cache'
$env:UV_PROJECT_ENVIRONMENT='D:\develop\aiknowledge\aiknowledge\.venv-local'
uv sync --python D:\develop\conda\python.exe
uv run pytest -q
uv run python -m compileall -q app tests
```

前端：

```powershell
cd ..\aiknowledge_frontend
npx tsc --noEmit --skipLibCheck
npm run build:h5
npx eslint src
npm run lint:style
```

后端测试采用 TDD，覆盖模型客户端、Embedding 维度/重试、文档解析与生命周期、空间/分类/分享权限、owner/public RAG scope、引用快照、连续追问、对话列表/删除、SSE、限流和 Origin 安全策略。Docker 不可用时仍可运行完整单元/API 测试；依赖恢复后再运行 `tests\runtime_public_e2e.ps1` 与 `tests\runtime_delete_cleanup.ps1` 做真实 Postgres/Redis/MinIO 验证。

## 主要接口

```text
GET    /health/live
GET    /health/ready
POST   /api/v1/spaces
GET    /api/v1/spaces
POST   /api/v1/spaces/{space_id}/documents
GET    /api/v1/spaces/{space_id}/documents
POST   /api/v1/owner/conversations
GET    /api/v1/owner/conversations?space_id={space_id}
GET    /api/v1/owner/conversations/{conversation_id}
POST   /api/v1/owner/conversations/{conversation_id}/messages
DELETE /api/v1/owner/conversations/{conversation_id}
POST   /api/v1/public/session
POST   /api/v1/public/conversations
POST   /api/v1/public/conversations/{conversation_id}/messages
```

`stream=true` 时消息接口返回 `text/event-stream`，事件顺序为若干 `delta`（`{"text":"..."}`）、`answer`（最终 DTO）和 `done`。`delta` 是服务端完成引用/权限校验后的安全增量，不会把未经校验的模型原始 token 提前暴露；公开接口的每个事件都不包含 citations、文件名或原文片段。

## Docker 故障排查

`no configuration file provided` 表示当前目录不是仓库根目录；先 `cd D:\develop\aiknowledge`。如果出现 `dockerDesktopLinuxEngine ... system cannot find the file specified`，说明 Docker Desktop Linux 引擎尚未启动，先从 Docker Desktop 重新启动引擎，再重试 `docker info`。如果旧 MinIO 标签被镜像源拒绝，当前 Compose 已使用 Quay 的固定 digest，不要改回不存在的 Docker Hub release 标签。
