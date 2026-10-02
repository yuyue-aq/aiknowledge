# V2 MVP 交付说明

日期：2026-10-02。分支：`codex/v2-mvp`。本轮仅开发 H5 与 Python 后端，复用 V1 登录与基础设施，不开发小程序。源码与测试已完成本轮实现；整体 MVP 尚未通过真实运行时验收。详见《V2MVP开发验收记录》及 `eval/v2/ui/验收映射.md`。

## 已实现的业务链路

1. 上传资料，查看处理状态、当前版本与原文证据。更新时保留旧活动版本，成功后切换；失败版本可以重试。删除后立即退出检索，后台幂等清理历史对象。
2. 独立输入问题，执行 Embedding → 余弦检索 → Top K。查看排名、分数、来源区间与耗时，再把问题带入可信问答。独立检索不调用 LLM。
3. 问答使用同一检索服务，保留引用快照；来源失效时明确提示。公开访客只看到回答，服务端在检索、生成与 SSE 输出阶段复核有效范围。
4. 提交反馈原因与说明，人工修正、补充资料，将问题和修正答案带入复测题草稿。
5. 编辑问题、标准答案和精确证据，保存固定题集版本，异步运行、查看进度、人工评分、比较同一题集的两次运行。任务有检查点、租约、配置/知识变化保护与补投恢复。

不引入 LangChain、LlamaIndex、混合检索、Reranker、自动评分或 Agent。所有模型失败显示真实错误；问答不会回退为固定演示答案。

## 启动与部署

运行环境沿用仓库锁文件：Python ≥3.14、FastAPI、SQLAlchemy async、Postgres/pgvector、Redis、Celery、MinIO；前端 Taro 4.2.1、React、TypeScript、Yarn 1.22.22。

Docker Desktop 的 Linux 引擎可用后，在仓库根目录执行：

```powershell
docker compose --env-file aiknowledge\.env up -d --build
docker compose --env-file aiknowledge\.env ps
```

真实模型密钥仅保存在未提交的 `.env` 中。Compose 包含 API、worker、beat 和前端；API 启动执行数据库迁移。最新迁移为 `20261002_0022`，包含来源区间/revision、检索记录、评测快照/租约、文档版本来源与删除清理标记。对既有数据库升级前应先备份并在隔离测试库验收；已在独立空库及含历史合成资料的测试库执行升级，现有 V1 数据库未修改。

beat 每 60 秒扫描待补投/租约过期的评测及未完成的对象清理，扫描有界；worker 执行任务，beat 不调用模型。部署仅启动 API 而缺少 worker/beat 会缺少后台处理与补偿。

访问 H5：`http://localhost:10086`；健康检查：`http://localhost:8000/health/ready`；接口文档：`http://localhost:8000/docs`。共享链接指向 H5 公开页面。

## 新增接口入口

以下路径均在 `/api/v1` 下；拥有者诊断/证据接口严格校验空间所有权，资料更新沿用编辑权限。

| 用途 | 接口 |
| --- | --- |
| 独立检索 | `POST /owner/spaces/{space_id}/retrieval-runs` |
| 已保存检索 | `GET /owner/retrieval-runs/{run_id}` |
| 资料详情与当前证据 | `GET /owner/spaces/{space_id}/documents/{document_id}` |
| 当次评测候选证据 | `GET /owner/eval-runs/{run_id}/results/{result_id}/evidence` |
| 上传新版本 | `POST /documents/{document_id}/versions` |
| 重试失败版本 | `POST /documents/{document_id}/versions/{version_id}/retry` |
| 当前题集异步运行 | `POST /spaces/{space_id}/eval-runs/async` |
| 固定版本异步运行 | `POST /eval-versions/{version_id}/runs/async` |
| 查询进度与结果 | `GET /eval-runs/{run_id}` |
| 恢复失败/过期任务 | `POST /eval-runs/{run_id}/retry` |

创建题集版本可传 `case_ids`，冻结选定的 1—50 题；未传时冻结当前全部题目。评分沿用 `PATCH /eval-results/{result_id}`。证据历史页读取当次候选 ID，不重新检索；资料已删除、过期或版本失效时返回不可用提示。

## 测试与评测复现

```powershell
cd aiknowledge
.\.venv-local\Scripts\python.exe -m pytest -q
cd ..\aiknowledge_frontend
yarn test
node node_modules/typescript/bin/tsc --noEmit --skipLibCheck
node node_modules/eslint/bin/eslint.js src/components src/pages/index/index.tsx src/pages/public/public.tsx
yarn lint:style
$env:npm_config_script_shell='C:\Windows\System32\cmd.exe'
yarn build:h5
```

不依赖 LLM/数据库的真实本地检索基线：在根目录用已安装 PyTorch/Transformers 的 Python 执行：

```powershell
python aiknowledge/examples/local_retrieval_baseline.py --model-path models/embedding/bge-large-zh-v1.5 --dataset eval/v2/gold_cases.json --output eval/v2/local_retrieval_tuning_baseline.json
```

实际报告：35 题调优集中的 28 道有正向文档标注题，文档 Recall@5 / Hit@5 均为 1.0；7 道负例仅记录候选。15 道保留题未运行。该结果是小型合成资料上的 Transformers CLS 检索结果，不代表生产 FlagEmbedding、数据库权限、生成正确率、拒答正确率或真实业务效果。

真实 50 题运行步骤见 `eval/v2/README.md`。必须映射实际入库的文档/版本 UUID、冻结 35/15 两个题集，并人工评分；不能把合成 UI 指标作为基线。

## 尚需完成的验收

- 人工回答评分、反馈修复案例和质量报告完善。
- 完整 27 场景逐屏对照、真实端到端测试及实际目标用户试用。

当前变更未提交、未推送、未部署到正式环境，未删除既有真实资料。隔离验收环境已接入用户授权的 DeepSeek Flash。

2026-10-02 续验收：真实迁移、生产 BGE/pgvector、50 题标注绑定、版本切换、访问过滤、异步故障检查点、所有版本对象清理及真实 H5 交互已通过。用户已取消单价限制并指定 DeepSeek Flash，正式模型名统一为 `deepseek-flash`，非思考模式保持不变；按 RED→GREEN 修改默认模型名，完整后端回归 **342 passed / 17.83s**。真实生成结果单独记录在 `eval/v2/runtime`，不能与此前缺少密钥的故障测试混淆。

真实 Flash 的35题基线、同配置35题复测和首次15题保留集均已完成，调用失败与越权引用均为0，正向标注文档/证据 Recall@12 均为1.0。调优集有1题可回答问题持续拒答，人工 Answer Accuracy 保持未知；逐题输出及边界见 `eval/v2/runtime/DeepSeekFlash真实验收报告.md`。H5 重试已返回“14天”和有效原文引用。

推送前最新检查：后端346项通过、前端25项及类型/静态/样式/设计审计/H5构建通过。公开绕权命令已增加确定的前置拒答，真实API无模型用量。角色称呼题仍需确认“管理员”是否指“拥有者”，暂未提交或推送；最终检查记录见 `V2推送前检查.md`。


## 2026-10-02 个人与团队权限检查结论

前文“角色待确认、暂不推送”是历史检查记录。用户现已明确个人仅拥有者管理，团队一位拥有者、多位管理员；团队管理员可查看原文引用、使用检索调试、管理资料与评测。新建空间提供个人/团队选择，成员设置仅向团队拥有者显示角色调整，后台统一校验。新迁移 `20261002_0022` 保留既有协作并约束唯一拥有者。

最新后端348项、前端25项、类型/静态/样式检查、strict audit及H5生产构建通过。真实角色8项与旧数据升级/唯一拥有者约束通过，见 `eval/v2/runtime/space-roles-report.json`、`role-migration-report.json`。角色政策合成资料04/08按用户决议修订；旧冻结版本/失败及中间结果保留。最新35题真实回归 `flash-tune-role-policy.json` 返回状态全部匹配、调用失败及越权引用均0、正例文档/证据Recall@12=1.0。35题为调优集结果；重复15题明确标记回归，不视为新的盲测。人工答案评分仍未完成。

本次提交不表示正式部署、真实用户试用、全场景原型逐屏对照或公开SSE并发撤销验收已完成。最终提交与推送结果以远程分支及最终回复为准。

最终15题角色政策回归 `flash-holdout-role-policy-regression.json`：12回答、1证据不足、2冲突，调用失败与越权引用0，状态15/15匹配，正例Recall@12=1.0。这是重复回归，不是新的盲测；详细报告见 `eval/v2/runtime/角色政策最终回归报告.md`。
