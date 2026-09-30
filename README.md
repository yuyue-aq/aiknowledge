# 知溯 AiKnowledge MVP

> 2026-09-30 验收结论：V1 尚未全部完成。已修复问题、当前回归结果与 P0 缺口见 [V1验收报告](./V1验收报告.md)。最新迁移为 `20260929_0016`，部署本轮修复需执行 `alembic upgrade head`。

这是一个以 DeepSeek Flash + `BAAI/bge-large-zh-v1.5` 为核心的可信知识工作台 MVP：资料进入私有对象存储，后台解析并生成 1024 维向量，所有者问答保留引用快照，公开访客只能检索分享链接当前开放分类。

## 当前交付范围

- 后端：`aiknowledge/`，FastAPI、SQLAlchemy async、pgvector、Redis/Celery、MinIO。
- 前端：`aiknowledge_frontend/`，Taro 4.2.1 + React + TypeScript，可构建 H5/小程序。
- 模型：DeepSeek `deepseek-flash`（瞬时网络/5xx 错误有限重试）；Embedding `BAAI/bge-large-zh-v1.5`，默认 1024 维，支持批量生成。
- 问答：普通 JSON 与 SSE 增量事件；前端支持 `AbortController` 停止生成、SSE 不可用时降级 JSON；连续追问只使用最近用户问题，不把回答当作事实证据。
- 安全：公开会话/提问进程级限流、可信 Origin 校验、安全响应头、公开响应不包含来源字段。
- 用户登录/注册、刷新令牌和空间成员权限：已接入；公开访问仍通过短期会话和分享范围控制。生产环境请使用独立密钥并完成 HTTPS/日志/备份配置。
- 外部知识来源：支持登记网页、Markdown 仓库地址和 FAQ CSV/TSV/XLSX 地址，手动同步后复用普通文档的解析、向量化与权限链路。
- 运营增强：支持公开访问统计、访客问题审核/隐藏、来源 Origin 白名单、评测集版本快照、批量文档上传、公开 Token 查询和嵌入脚本。

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

   Worker 默认使用 4 个 Celery 子进程，并将模型线程限制为 1；每个子进程会加载一份本地 BGE 模型。CPU 较弱时可在 `aiknowledge\\.env` 下调 `AIKNOWLEDGE_WORKER_CONCURRENCY`，内存充足且需要并行 ingest 时再调高。

4. 查看应用日志：

   ```powershell
   docker compose --env-file aiknowledge\.env logs -f api worker frontend
   ```

5. 停止运行时（不会删除 Postgres/MinIO 命名卷）：

   ```powershell
   docker compose --env-file aiknowledge\.env down
   ```

   前端 H5 已在 Nginx 容器内构建并托管，不需要再运行 IDE 中的 `npm run dev:h5` 或本机 Uvicorn。Compose 默认将前端 API 地址编译为 `http://localhost:8000/api/v1`；如果修改了 API 端口，请同步修改 `.env` 中的 `TARO_APP_API_BASE` 和 Compose 端口映射后重新执行 `up -d --build`。跨域地址必须同时加入 `AIKNOWLEDGE_CORS_ALLOWED_ORIGINS`。

## 备份与恢复

数据库和 MinIO 私有桶需要成对备份。`ops\backup.ps1` 优先使用本机 `mc`，没有安装时会自动使用 API 容器内的 MinIO SDK 生成 tar 归档；`ops\restore.ps1` 默认拒绝执行，必须显式传入 `-ConfirmRestore`。完整说明见 [`ops/README.md`](ops/README.md)。

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
Copy-Item .env.example .env
npm test
npx tsc --noEmit --skipLibCheck
npm run build:h5
npx eslint src
npm run lint:style
```

后端测试采用 TDD，覆盖模型客户端、Embedding 维度/重试、文档解析与生命周期、空间/分类/分享权限、owner/public RAG scope、引用快照、连续追问、对话列表/删除、SSE、限流和 Origin 安全策略。Docker 不可用时仍可运行完整单元/API 测试；依赖恢复后再运行 `tests\runtime_public_e2e.ps1` 与 `tests\runtime_delete_cleanup.ps1` 做真实 Postgres/Redis/MinIO 验证。

Docker 运行链路的安全冒烟测试使用纯合成夹具，不会上传项目文档：

```powershell
$fixture = "D:\develop\aiknowledge\aiknowledge\tests\runtime_synthetic_public.txt"
& .\aiknowledge\tests\runtime_public_e2e.ps1 -FixturePath $fixture
& .\aiknowledge\tests\runtime_delete_cleanup.ps1 -FixturePath $fixture
```

`tests\runtime_eval_baseline.ps1` 会读取项目资料并调用配置的第三方 DeepSeek 服务，脚本默认拒绝执行；只有在明确授权资料外发后，才显式追加 `-AllowExternalData` 运行。

两个 Compose 安全冒烟脚本每次生成独立账号与随机密码，结束时停用测试账号并撤销其刷新令牌；密码不会保存到文件或日志。清理会核对用户 ID、测试邮箱和显示名称。若曾运行旧版脚本，在后端环境执行以下命令，可停用旧固定测试账号（保留数据，重复执行安全）：

```powershell
cd aiknowledge
uv run python ..\ops\disable_runtime_accounts.py --legacy
```

前端本地配置从 `.env.example` 复制；`TARO_APP_*` 会公开到浏览器，只能放 API 地址等公开配置。实际环境文件、IDE 设置、备份和浏览器测试产物已加入共享忽略规则。

## 主要接口

```text
GET    /health/live
GET    /health/ready
POST   /api/v1/spaces
GET    /api/v1/spaces
GET    /api/v1/spaces/{space_id}/usage
GET    /api/v1/spaces/{space_id}/public-questions
POST   /api/v1/spaces/{space_id}/documents
GET    /api/v1/spaces/{space_id}/documents
GET    /api/v1/spaces/{space_id}/sources
POST   /api/v1/spaces/{space_id}/sources
PATCH  /api/v1/sources/{source_id}
POST   /api/v1/sources/{source_id}/sync
GET    /api/v1/spaces/{space_id}/eval-versions
POST   /api/v1/spaces/{space_id}/eval-versions
POST   /api/v1/eval-versions/{version_id}/runs
GET    /api/v1/spaces/{space_id}/eval-runs/compare?baseline_run_id={id}&candidate_run_id={id}
GET    /api/v1/spaces/{space_id}/public-analytics
GET    /api/v1/spaces/{space_id}/public-questions
POST   /api/v1/owner/conversations
GET    /api/v1/owner/conversations?space_id={space_id}
GET    /api/v1/owner/conversations/{conversation_id}
POST   /api/v1/owner/conversations/{conversation_id}/messages
DELETE /api/v1/owner/conversations/{conversation_id}
POST   /api/v1/public/session
POST   /api/v1/public/query
POST   /api/v1/public/conversations
POST   /api/v1/public/conversations/{conversation_id}/messages
```

`stream=true` 时消息接口返回 `text/event-stream`，事件顺序为若干 `delta`（`{"text":"..."}`）、`answer`（最终 DTO）和 `done`。`delta` 是服务端完成引用/权限校验后的安全增量，不会把未经校验的模型原始 token 提前暴露；公开接口的每个事件都不包含 citations、文件名或原文片段。

### 公开 Token 与嵌入

在空间设置中生成分享链接后，可选填来源 Origin 白名单（例如 `https://docs.example.com`）。公开会话、Cookie 问答以及 `POST /api/v1/public/query` 都会统一执行白名单校验；未配置白名单时不限制 Origin，但仍需要有效分享 Token。

网页嵌入脚本位于构建产物 [`aiknowledge_frontend/dist/aiknowledge-embed.js`](aiknowledge_frontend/dist/aiknowledge-embed.js)。将脚本部署到静态站点后，在业务页面使用：

```html
<div id="aiknowledge-widget"></div>
<script src="/aiknowledge-embed.js"></script>
<script>
  AiKnowledgeEmbed.mount({
    token: "创建分享链接时获得的 token",
    target: "#aiknowledge-widget",
    publicUrl: "http://localhost:10086",
    height: "620px"
  });
</script>
```

脚本只把 Token 放入公开页面 iframe 的 URL，不向脚本服务器发送 Token；生产环境请使用 HTTPS、短期 Token 和明确的 Origin 白名单。

### 批量导入与评测版本

批量上传使用 `POST /api/v1/spaces/{space_id}/documents/batch`，字段名为 `files`，单次最多 20 个文件，返回 `items` 与逐文件 `failures`，允许部分成功。评测页可以保存当前题集快照并按版本运行，版本记录包含题目、预期答案和证据 ID，避免后续编辑题集改变历史结果。

## Docker 故障排查

`no configuration file provided` 表示当前目录不是仓库根目录；先 `cd D:\develop\aiknowledge`。如果出现 `dockerDesktopLinuxEngine ... system cannot find the file specified`，说明 Docker Desktop Linux 引擎尚未启动，先从 Docker Desktop 重新启动引擎，再重试 `docker info`。如果旧 MinIO 标签被镜像源拒绝，当前 Compose 已使用 Quay 的固定 digest，不要改回不存在的 Docker Hub release 标签。
