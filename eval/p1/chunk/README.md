# D结构分块与重建复现

本目录只用于10087/API8001/aiknowledge_p1独立测试，不用于用户重要资料或正式部署。

`build_materials.py`生成五个新虚构服务的PDF/MD/TXT和50题，首次生成后以manifest.json冻结字节哈希/标答，不能在评测过程中重生成。PDF采用本地中文字体，已由Poppler渲染及真实解析验证。材料中的服务期限不代表真实运营，也不能混入原版14天/30天的500题空间。500-materials为旧档案的隔离副本。

流程：

1. `live_check.py seed` 创建独立账号及三格式空间，上传15份新资料，存凭证到忽略的.auth/p1-chunk。重复上传准备会复用该测试空间。
2. `live_check.py compare` 同题50条检索对照，预览及分页中核对全源区间、hash/token；实际重建15文档后逐条核对入库内容，再测检索。运行时PYTHONPATH指向仓库aiknowledge后端目录。
3. `gate_check.py seed`创建另一个独立长段落页面空间；`gate_check.py gates`实测原子激活、重复、旧预览、故障恢复及角色/匿名边界。为确定中间状态短暂暂停测试Worker并finally恢复，故障SQL仅针对本次新建虚构版本。
4. `ui_check.cjs`在真实Edge操作已批准两列页面、分页、取消、受控503重试、390px、确认和实际Worker；需要Playwright的NODE_PATH。成功请求没有模拟。
5. `strategy_check.py`复核三格式结构索引上的真实RRF与BGE重排；`qualification_check.py`补过期/未来生效/跨空间/删除界限，时间恢复，仅删除本次临时文档。
6. `run_500.py dense`在另三个新私密空间使用原档案、先重建结构索引再运行500题；`judge_500.py dense --watch`独立模型辅助评分。原B/C账号、状态、数据与分数不覆盖。
7. `report_500.py dense`在全部完成后检查来源与运行快照；`inspect_low_scores.py`、`annotate_low_scores.py`保留低分证据；`compare_500.py`做同标答观察，D知识版本/片段ID不同，不声称严格同知识清单因果收益。

Docker执行文件可通过AIKNOWLEDGE_EVAL_DOCKER设置。产品API与Worker必须已健康，模型缓存已准备。完整产物在output/p1-chunk，JSON小型证据在evidence，凭证不进入Git。人工方法与最终实绩见仓库根目录P1阶段D文档。
