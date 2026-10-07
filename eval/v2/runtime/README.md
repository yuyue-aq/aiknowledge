# 2026-10-02 真实隔离运行时验收

本目录包含真实 Postgres/pgvector、MinIO、Celery、FlagEmbedding 及 API 的验收脚本与结果。所有内容为合成资料，现有 V1 数据、服务和卷未修改。

## 模型调用授权

2026-10-02 用户明确取消此前 **0.5 元/百万 token** 单价限制，并指定使用 **DeepSeek Flash**。模型统一配置为 `deepseek-flash`，保持非思考模式；已有本地密钥只通过调用进程环境注入隔离服务，不写入仓库或报告。官方价格核对保留在 `price_check.json`。

下表及 `ui-real-generation-blocked.png` 等既有记录产生于接入密钥之前，验证的是**故障持久化**，不作为正常回答质量基线。后续真实 Flash 生成结果单独记录，避免混淆历史故障测试和回答质量。

## 启动和复现

从仓库根目录执行；需要 Docker Linux engine 与已有 `aiknowledge-api:latest` 依赖镜像。本配置挂载当前源码，运行库为实际现有镜像，不代表重新构建部署镜像已验收。

```powershell
docker compose -p aiknowledge-v2-acceptance -f eval/v2/compose.runtime.yaml up -d
aiknowledge\.venv-local\Scripts\python.exe eval/v2/runtime/check_retrieval.py
aiknowledge\.venv-local\Scripts\python.exe eval/v2/runtime/check_lifecycle.py
docker compose -p aiknowledge-v2-acceptance -f eval/v2/compose.runtime.yaml exec -T api python /runtime/check_cleanup.py
```

API 仅绑定 `127.0.0.1:18000`，数据库与对象存储使用独立命名卷。测试账号凭据只在内存中使用，不存入报告。脚本每次创建新合成空间；报告只保存最近一次结果。停止可运行相同 Compose 命令的 `down`，不加 `-v` 则保留测试数据。

历史升级另使用该隔离 Postgres 的 `v2_upgrade_test` 数据库：先升级到 `20260929_0016`，执行 `legacy_seed.sql`，再升级到 head，运行 `check_upgrade.py`。历史升级夹具只应在新的空测试数据库执行一次；验证脚本可重复执行。

## 实测结果

| 报告 | 实际结果 | 边界 |
| --- | --- | --- |
| `upgrade_report.json` | 6 项检查通过；0016→0021、历史版本/片段保留、活动来源回填、未知坐标、并发 revision 与已知向量余弦 | 历史合成数据升级，未升级现有 V1 数据 |
| `retrieval_report.json` | 38 项检查通过；23 份真实入库、50 题绑定实际版本/区间/hash、35/15 冻结版本、权限/分类/撤销/停用过滤 | 调优集 OWNER 正向标注 23 题文档 Recall@5=1.0；不代表 PUBLIC 检索或回答准确率；保留题未运行 |
| `lifecycle_report.json` | 17 项检查通过；上传签名拒绝、失败保留旧版本、失败重试、成功切换、过期/删除过滤、异步检查点与历史证据失效 | 实际生成故障保持 FAILED，保留真实候选与检索指标；无生成质量结论 |
| `cleanup_report.json` | 原版、失败版、新版共 3 个源对象均不可读，删除完成标记已写入 | API 删除加 beat 补偿的真实结果；没有删除既有用户数据 |

初次脚本执行出现两处脚本错误：把关闭全部分类的会话拒绝误认为应返回空分类；误用了 `/documents/{id}` 而非 `/availability` 更新可用性。已修正脚本并从新合成空间完整重跑。签名无效 PDF 的 422 是正确拒绝，解析失败测试另使用有 PDF 签名的畸形资料。

真实运行还发现 Worker 每份资料重新初始化模型。按 RED→GREEN 实现同进程/同配置复用，并验证 PID/配置隔离和跨顺序事件循环编码；后端完整回归 **341 passed / 19.46s**。实际后续资料任务处理约 0.5—1.3 秒，不承诺其他硬件的性能。

## 真实浏览器

使用最终 H5 构建，经浏览器请求转发连接该真实隔离 API。只替换请求目标端口，没有模拟响应。测试内容为合成资料。

- `ui-real-upload.png`：实际上传，Worker 处理后显示可用。
- `ui-real-retrieval.png`：实际 Top K 与原文，截图查询耗时 608 ms。
- `ui-real-generation-blocked.png`：缺少生成密钥时显示真实失败与重试入口。
- `ui-real-async-completed.png`：实际运行完成 1/1，调用失败 1，未假装回答成功。
- `ui-real-grade.png`：人工标记错误并保存“未配置生成密钥”的说明。
- `ui-real-document-mobile.png`：390×844 资料详情，实际来源区间，无横向溢出。

仍需：人工回答评分与反馈修复、生成与公开 SSE 的真实并发撤销、完整原型逐屏对照、实际目标用户试用，以及最终部署镜像构建验收。

## 已接入 DeepSeek Flash

取消预算限制后完成实际生成：`flash-tune-baseline.json`（35题）、`flash-tune-retest.json`（同版本/同配置35题）、`flash-holdout-acceptance.json`（首次15题保留集）。三次均完成、无调用失败、无越权引用；正向标注的文档与证据 Recall@12 均为1.0。调优基线和复测均有1题可回答问题被拒答，详见 [真实验收报告](DeepSeekFlash真实验收报告.md)。人工回答评分未完成，Answer Accuracy 保持未知。

H5 实际重试已显示 Flash 的“14天”回答和原文引用：`ui-real-flash-answer.png`。最新完整后端回归342项通过。此时剩余的是人工评分/反馈修复、真实并发撤销、完整原型对照、用户试用和部署验收。

推送前补充复查：`flash-tune-roles-fixed.json` 保存35题修复尝试，调用失败/越权引用为0，但角色称呼题仍拒答，拒答状态指标也有波动。该文件名不代表通过。角色语义已向用户请求确认，暂不推送；不得把单项通过当作稳定修复。公开绕权命令另增加前置拒答回归，正常权限说明问题仍可检索。详见仓库 `V2推送前检查.md`。

重新启动真实生成环境时，使用 `docker compose --env-file aiknowledge/.env -p aiknowledge-v2-acceptance -f eval/v2/compose.runtime.yaml up -d`，然后 `exec -T api python /runtime/check_generation.py --smoke`。密钥只能留在被忽略的本地 `.env`。若重新跑缺少密钥的历史故障夹具，应先以无密钥配置启动，不可在已接入模型的环境中期待同样的故障结果。保留集不应用于重复调参。


## 2026-10-02 个人与团队权限检查结论

前文“角色待确认、暂不推送”是历史检查记录。用户现已明确个人仅拥有者管理，团队一位拥有者、多位管理员；团队管理员可查看原文引用、使用检索调试、管理资料与评测。新建空间提供个人/团队选择，成员设置仅向团队拥有者显示角色调整，后台统一校验。新迁移 `20261002_0022` 保留既有协作并约束唯一拥有者。

最新后端348项、前端25项、类型/静态/样式检查、strict audit及H5生产构建通过。真实角色8项与旧数据升级/唯一拥有者约束通过，见 `eval/v2/runtime/space-roles-report.json`、`role-migration-report.json`。角色政策合成资料04/08按用户决议修订；旧冻结版本/失败及中间结果保留。最新35题真实回归 `flash-tune-role-policy.json` 返回状态全部匹配、调用失败及越权引用均0、正例文档/证据Recall@12=1.0。35题为调优集结果；重复15题明确标记回归，不视为新的盲测。人工答案评分仍未完成。

本次提交不表示正式部署、真实用户试用、全场景原型逐屏对照或公开SSE并发撤销验收已完成。最终提交与推送结果以远程分支及最终回复为准。

最终15题角色政策回归 `flash-holdout-role-policy-regression.json`：12回答、1证据不足、2冲突，调用失败与越权引用0，状态15/15匹配，正例Recall@12=1.0。这是重复回归，不是新的盲测；详细报告见 `eval/v2/runtime/角色政策最终回归报告.md`。
