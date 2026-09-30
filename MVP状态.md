# 知溯 AiKnowledge 当前状态（2026-09-30）

## 交付结论

**V1 尚未全部完成。** 本轮后端 **212 passed**、前端新增 **18 passed**，类型/规范/H5 构建通过，并修复了登录刷新、伪成功提示、SSE、标签筛选、队列失败、数据库失败码和分享路由问题。但部分 P0 功能仍只有后端接口，空间删除物理清理未闭环；Docker 引擎不可用，最新迁移与真实运行时未验收。完整清单、证据与优化建议见 [V1验收报告](./V1验收报告.md)。

## 已有实现与历史验证（不等于 V1 整体验收通过）

| 范围 | 状态 | 验证 |
| --- | --- | --- |
| DeepSeek Flash 结构化回答、拒答、引用校验与有限重试 | 完成 | `test_deepseek_client.py`、`test_rag_service.py` |
| BGE-large-zh-v1.5（1024 维、批量、超时/重试） | 完成 | `test_bge_client.py` |
| PDF/DOCX/Markdown/TXT/CSV/TSV/XLSX/PPTX 上传、解析、切块、异步任务与失败重试 | 完成 | 文档解析、格式边界、任务和运行测试 |
| 文档版本原子切换、负责人、生效/失效时间、启停、删除清理 | 完成 | 文档生命周期测试；迁移 `20260917_0010` |
| 私密/公开空间、公开分类、默认入口、密码、有效期、访客提问上限 | 完成 | `test_space_*`、`test_public_*` |
| Owner/Public 对话、连续追问、历史引用、SSE 与 JSON 降级 | 完成 | `test_conversation_*` |
| 注册、登录、刷新、退出、成员邀请和 Owner/Editor/Member 权限矩阵 | 完成 | `test_auth_*`、`test_membership*`、权限回归 |
| 反馈筛选、人工修正、审核状态、数据用途和隐私标记 | 完成 | `test_feedback_*` |
| 知识标签、文档打标、标签筛选和文档搜索 | 完成 | `test_tag*`、`test_document_search.py` |
| 匿名访客提问记录 | 完成 | `test_public_questions.py`、`test_space_api.py` |
| FREE/PRO/TEAM 套餐、文档/成员/每日提问额度与前端用量展示 | 完成 | `test_usage.py`、`test_usage_api.py` |
| Docker Compose API/Worker/Postgres/Redis/MinIO/前端启动链 | 完成 | `/health/live`、`/health/ready`、合成数据 e2e |
| 安全边界、Origin/CSRF、限流、安全响应头和公开 DTO 脱敏 | 完成 | `test_security.py`、`test_app_infrastructure.py` |
| P2 来源登记与手动同步（网页、Markdown 仓库、FAQ 表格） | 完成 | `test_sources.py`、`test_sources_api.py` |
| P2 公开访问统计、访客审核/隐藏、Origin 白名单、Token 查询和嵌入脚本 | 完成 | `test_public_analytics.py`、公开接口回归、H5 构建 |
| P2 评测集版本快照、历史运行题目快照、运行指标对比和批量导入 | 完成 | `test_evaluation_*`、`test_document_api.py` |
| 评测历史结果保护（题目有结果时禁止删除） | 完成 | `test_evaluation_service.py`、迁移 `20260917_0015` |

## 当前验证结果（2026-09-30）

- 后端：`212 passed`；前端：`18 passed`，TypeScript、ESLint、Stylelint、H5 构建通过。
- 浏览器：7 项合成 API 场景通过；覆盖公开设置失败回退、分享路由、公开会话及窄屏，未替代真实后端端到端。
- 迁移：代码 head 为 `20260929_0016`；离线 SQL 与失败码一致性检查通过，尚未应用到真实数据库。
- Docker：Linux engine 命名管道不可用，真实端到端未复测。
- P0 缺口：空间/分类编辑删除入口、原文件下载入口、对话历史管理、反馈原因与说明、空间删除后异步清理等，详见验收报告。

## 历史验证结果（2026-09-17，仅供追溯）

- 后端：`208 passed`；迁移已从数据库升级至 `20260917_0015`。
- Docker：Owner/Public 合成问答均返回 `ANSWERED`，公开响应不含引用字段；删除后 MinIO 对象消失、文档返回 404。
- 前端：TypeScript、ESLint、Stylelint、H5 生产构建通过；Nginx H5 路由回退已配置。
- 真实资料评测：已按授权完成 12 题 DeepSeek Flash 基线，结果为 4 `ANSWERED`、7 `INSUFFICIENT_EVIDENCE`、1 `OUT_OF_SCOPE`、0 `FAILED`；尚未进行人工 reviewer 复核，因此不能将状态分布当作正确率。

## 仍需外部/运营验收的事项

- 至少 5 名目标用户的真实试用与反馈记录；
- 在隔离环境执行一次数据库和 MinIO 备份恢复演练（脚本位于 `ops/`，恢复命令有显式破坏性确认）；
- 公网部署前配置 HTTPS、密钥轮换、日志采集和备份保留策略；
- 扫描 PDF 目前会明确标记为 `SCANNED_DOCUMENT` 并拒绝入库，尚未接入 OCR/图像理解模型；企业网盘/知识平台连接器、自动生成评测题仍需真实凭据和产品规则后排期。

## 回归命令

```powershell
cd D:\develop\aiknowledge\aiknowledge
& .venv-local\Scripts\python.exe -m pytest -q
& .venv-local\Scripts\python.exe -m compileall -q app tests

cd ..\aiknowledge_frontend
npm test
npx tsc --noEmit --skipLibCheck
npx eslint src
npm run lint:style
npm run build:h5
```
