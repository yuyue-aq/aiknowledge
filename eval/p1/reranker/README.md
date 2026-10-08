# 阶段C复现资料

模型固定为BAAI/bge-reranker-v2-m3，revision见`evidence/model-manifest.json`。在仓库根目录以后端Python运行`tools/prepare_reranker_model.py`，下载/校验缓存，再通过`tools/prepare_p1_preview.py`和`compose.p1.yaml`启动隔离预览。模型不进入Git或构建上下文。

以下脚本只面向本机10087/API8001和aiknowledge_p1，不用于正式生产。需要httpx、可运行的Docker，以及已就绪的预览API/Worker。应先保留原始产物，避免重复运行覆盖某次验收证据。

| 脚本 | 作用与前置条件 |
|---|---|
| `live_check.py` | 使用冻结40题创建虚构账号、独立团队空间并上传4份新资料，逐题比较同一完整候选池、保存契约及来源停用。创建测试凭证到忽略的.auth/p1-reranker；结果到output/p1-reranker/live。 |
| `ui_check.cjs` | live_check后使用上述测试账号，在真实Edge中验两列/分数/来源、错误恢复、取消、390px和问答策略；需要Playwright及Edge。成功请求为真实服务，503/延迟仅用于故障场景。 |
| `runtime_check.py` | 依赖阶段B已有虚构运行夹具与.auth/p1-rrf，检查模型策略公开范围、历史来源与真实Worker。 |
| `audit_check.py` | 依赖B运行夹具，检查真实RagRun中的模型配置、候选/上下文审计与公开文件名边界。 |
| `scope_check.py` | 依赖B独立演示空间，暂改其团队角色、时间和活动版本并恢复；不操作旧500题空间或用户资料。 |
| `run_500.py hybrid_rerank` | 依赖B保存的output/p1-rrf/500/state.json及其纯虚构账号、固定原版PDF/MD/TXT；同一版本逐题校验指纹。最多三空间并行，各空间串行。使用独立C输出目录，不覆盖B结果。 |
| `judge_500.py hybrid_rerank --watch` | 独立DeepSeek Flash辅助评分，沿用固定标准；保存原分和理由，含75次前置问答的产品调用不计入500题得分。 |
| `report_500.py hybrid_rerank` | 等作答和评分全部500条后，核对数据库候选/来源/模型输入及资料指纹，输出原分与复核分报告。需要Docker环境变量AIKNOWLEDGE_EVAL_DOCKER指向可执行文件。 |
| `compare_500.py` | 同一500题及标准/资料版本的Dense、RRF、C逐题差异；先生成C报告，且保留B的reviewed_results/summary/source-manifest。 |
| `inspect_low_scores.py` / `annotate_low_scores.py` | 提取低分题候选与真实上下文；对本轮6道失败的缺失事实作明确原文词句定位，区分候选/上下文/生成问题，不改评分。 |

旧500题用原版14天/30天；新40题四份规则中的17/23/31/41天属于另一数据集。禁止将两组混入同一空间，或修改标答提高分数。模型辅助评分有同源偏差，引用/ID完整性与语义正确率是不同指标。

`evidence`只收录脱敏、可审阅的小型记录。完整500题原始请求、答案、引用、辅助评分理由和截图在忽略的output目录，凭证在.auth目录，模型在tmp/models目录。完整报告及人工验收文档位于仓库根目录。
