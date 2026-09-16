# MVP 当前状态（2026-09-15）

## 本轮已完成

| 范围 | 状态 | 验证 |
|---|---|---|
| BGE-large-zh-v1.5（1024 维、批量、超时/重试） | 完成 | `test_bge_client.py` |
| DeepSeek Flash 结构化回答、引用校验、拒答与瞬时错误有限重试 | 完成 | `test_deepseek_client.py`、`test_rag_service.py` |
| 文档上传、解析、切块、异步任务、版本切换和删除清理 | 完成 | 文档/运行测试 |
| 空间、分类、分享链接及公开范围实时校验 | 完成（单工作区） | `test_space_*`、`test_conversation_*` |
| Owner/Public 对话、历史引用、删除、对话列表 | 完成 | `test_conversation_service.py`、`test_conversation_api.py` |
| 连续追问（最近用户问题改写，回答不作为证据，改写长度受 2000 字符上限约束） | 完成 | `test_follow_up_rewrites_against_only_recent_user_question`、`test_follow_up_rewrite_keeps_the_normalized_question_limit_for_long_history` |
| Owner/Public SSE、增量事件、移动端 JSON 降级和 AbortController 停止 | 完成 | API SSE/断开测试、前端类型/构建 |
| 公开接口限流、Origin/CSRF 边界、安全响应头 | 完成（进程级限流） | `test_security.py`、`test_app_infrastructure.py` |
| 反馈、轻量评测 CRUD/运行/人工评分与 12 题评测清单 | 完成（题目需映射真实资料） | `test_evaluation_*`、`eval/mvp_eval_set.json` |
| Taro 前端原型、响应式布局、授权入口占位 | 完成（授权目录保留） | premium audit、TypeScript、H5 build、ESLint |

## 有意延期

- 用户注册、登录、刷新令牌、退出和真实 owner scope：你已明确要求“用户系统先不要做”。当前 owner 接口只适用于本地/受控演示环境，接入公网前不得把它视为已授权。

## 需要外部环境才能完成的验收

- Docker Desktop Linux 引擎当前在本机 WSL 中为 `Stopped`，因此本轮无法重新运行 Postgres/Redis/MinIO 容器级联调；代码和 Compose 配置检查已通过。引擎恢复后运行 `tests/runtime_public_e2e.ps1` 与 `tests/runtime_delete_cleanup.ps1`。
- 真实 10–20 题指标（正确率、引用率、延迟、成本）必须使用项目资料、有效分类 ID 和实际 DeepSeek key 运行，不能用演示文案冒充基线。
- 生产 HTTPS、备份恢复演练、至少 5 名用户试用属于部署/运营阶段，不在本地代码测试中伪造完成。

## 回归门禁

后端：`uv run pytest -q`（当前 126 passed）、`uv run python -m compileall -q app tests`。

前端：`npx tsc --noEmit --skipLibCheck`、`npm run build:h5`、`npm run build:weapp`、`npx eslint src`、`npm run lint:style`，并运行 frontend-design-premium strict audit。Stylelint 已针对 Taro 自定义宿主选择器和原型 token 记法配置兼容规则，并通过当前 SCSS 校验。
