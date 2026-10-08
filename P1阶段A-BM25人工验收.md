# P1阶段A：独立中文BM25 — 人工验收

日期：2026-10-07。开发分支codex/v2-non-mvp；阶段A已实现并完成TDD与隔离联调，阶段B的RRF融合尚未实现。

## 入口与准备

开发入口：[http://127.0.0.1:10087](http://127.0.0.1:10087/#/pages/index/index)。独立API8001、数据库aiknowledge_p1、Redis DB1及对象桶aiknowledge-p1-private。正式10086、aiknowledge数据库与main保持原实现，正式库仍为迁移0022，P1为0023。

1. 在10087注册一个专用测试账号；这里不共享10086账号。选择“团队”创建“BM25阶段A验收”空间（若只测个人功能也可选个人）。
2. 进入资料，上传下面三份文件，等状态全部“可用”：
   - [公开范围TXT](eval/p1/bm25/materials/01-公开范围.txt)
   - [库存规则MD](eval/p1/bm25/materials/02-库存规则.md)
   - [接口与租户TXT](eval/p1/bm25/materials/03-接口与租户.txt)
3. 点击左侧“检索调试”，在检索测试页选择“关键词检索 · BM25”，Top K选5。

不要把本验收文档或questions.json上传成知识来源。已有自动测试账号的数据仅供测试，不包含真实个人资料；你自己的账号需导入上述文件。

## A. 正常检索

| 输入 | 预期首条来源 |
|---|---|
| SCOPE_CHANGED | 01-公开范围.txt |
| v2.7.4 | 01-公开范围.txt |
| INV_STOCK_LOW | 02-库存规则.md |
| DUPLICATE_ORDER | 02-库存规则.md |
| INV-2026-0418 | 02-库存规则.md |
| tenant.alpha | 03-接口与租户.txt |
| AUTH_TOKEN_EXPIRED | 03-接口与租户.txt |

验收：显示真实片段、正确文件、排序和“BM25分数”；点击片段可看来源。分数不是概率，允许大于1，不能与余弦分数直接比大小。切换“向量检索”用相同问题观察排名差异，不要求向量检索一定出错。

BM25第一阶段只用于独立检索测试。“去可信问答”沿用现有问答方式，不宣称已使用BM25或RRF生成答案。查询不调用Embedding或LLM；上传阶段仍需生成文档向量以支持原有Dense路径。

## B. 空态、交互与错误

- [ ] 输入UNKNOWN_CODE_78219或v9.9.9，显示“没有匹配关键词的片段”，不随意补回向量结果。
- [ ] 清空问题，点击开始检索，出现输入提示且焦点回到问题。
- [ ] 点击输入框右侧×，问题、旧结果和旧错误清空，焦点返回输入。
- [ ] Enter可提交；输入中文时不应因输入法确认误提交。
- [ ] 检索过程中改变方式/Top K/问题，旧请求被取消，旧结果不能覆盖新状态。
- [ ] 切换其他空间，看不到前一空间的旧片段。
- [ ] 390px窄屏下控件可操作，无横向溢出，来源面板可滚动到达。

需要验证错误恢复时，可以暂时停止开发API（不停止正式服务）：

```powershell
docker compose -p aiknowledge-p1 -f compose.p1.yaml stop p1-api
# 在页面检索，应该出现真实失败提示，问题保留
docker compose -p aiknowledge-p1 -f compose.p1.yaml start p1-api
# 等API恢复后重试，正常得到真实结果
```

## C. 生命周期与权限

- [ ] 选择“关键词检索 · BM25”，停用01-公开范围.txt，再查SCOPE_CHANGED应无匹配结果；重新启用后恢复。
- [ ] 切换“向量检索”，停用后可以返回02/03的相似片段，但不得出现已停用的01文件。停用只排除该文件，不保证向量候选全为空。
- [ ] 更新该文件，将SCOPE_CHANGED改成SCOPE_RECHECKED。等新版本可用后，旧码无结果、新码能命中；最后上传原文件恢复。
- [ ] 新建另一个空间，仅在那里上传包含CROSS_SPACE_ONLY_51963的TXT。原空间查该码不能命中；新空间可以。
- [ ] 团队拥有者添加另一个已注册用户为管理员，管理员可进行关键词检索。
- [ ] 将管理员降级为成员，该用户不再能访问检索诊断；越权API请求被拒绝，不返回原文。
- [ ] 未登录/公开访客不应获得独立诊断和原文入口。

完整API契约：POST /api/v1/owner/spaces/{space_id}/retrieval-runs，JSON示例为{"question":"SCOPE_CHANGED","top_k":5,"strategy":"bm25"}。GET /api/v1/owner/retrieval-runs/{run_id}保存并返回实际strategy、score_kind和配置；来源失效后从items移除并记录unavailable_chunk_ids。

## 自动验证证据

- TDD红灯已复现：BM25模块未存在；API不支持策略时422；客户端未传策略。
- 绿灯：394项后端、29项前端测试通过，TypeScript/ESLint/Stylelint/H5构建通过；UI静态审计无发现。
- 真实API：停用、过期、未来生效、活动版本替换、历史来源失效、团队管理员/降级、未授权、跨空间及语料统计隔离均通过。
- 真实Edge浏览器：成功/无命中/空问题、清空焦点、键盘、错误恢复、加载宽度、取消迟到响应及390px布局通过。错误状态采用受控HTTP503、加载采用延迟转发；成功数据来自真实服务。
- 冻结15个新题，10调优/5保留。13个正例：BM25 Hit@1=13/13，Dense=12/13；两路Top3均包含13条标注证据。2个负例BM25均为空；Dense仍返回候选不等于生成会编造。

这里没有测新答案正确率，也不能把小语料结果推广为普遍召回改善；BM25未切为问答默认策略。旧500题的98%属于此前正式版本的生成回归，不能混入本阶段统计。

详细运行产物在output/p1-bm25，所有测试内容为虚构。关键词评分使用正IDF的Okapi BM25、k1=1.2、b=0.75，中文双字切分并保留完整ASCII标识符，范围内统计；当前上限5000个片段、200万正文字符，超限明确报错，不静默截断。它不是大规模全文索引或词典分词服务。

## 重启与复现预览

当前开发分支使用本文P1配置启动；重建正式10086时先切回main，再使用正式Compose。

须先运行正式Postgres/Redis/MinIO基础设施和原模型缓存。为了避免本机Git Bash把/api/v1转换成Windows路径，开发预览直接使用项目Taro CLI：

```powershell
cd D:\develop\aiknowledge\aiknowledge_frontend
$env:TARO_APP_API_BASE='/api/v1'
node node_modules/@tarojs/cli/bin/taro build --type h5
cd ..
# Docker CLI不在PATH时设置它的本地绝对路径
$env:AIKNOWLEDGE_EVAL_DOCKER='D:/develop/Docker/resources/bin/docker.exe'
& .\aiknowledge\.venv\Scripts\python.exe tools/prepare_p1_preview.py
```

停止仅P1服务：docker compose -p aiknowledge-p1 -f compose.p1.yaml stop。数据库和测试文件保留，不删除正式数据。临时.env与测试账号只放在忽略目录，不纳入Git。

## 下一阶段

人工验收本阶段后进入阶段B：Dense/BM25两路召回、RRF融合、三路实际排名对比，随后接入问答/评测并做同条件对照。保持Dense基线，收益不成立则不设为默认；真实Reranker排在后续阶段。
