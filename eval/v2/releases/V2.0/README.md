# V2.0 500题评测归档

2026-10-07。固定虚构资料，试用14天/保留30天。首个完整500题447/500（89.4%）；优化后490/500（98%），7条部分通过、3条追问错误。50道无依据题全部正确拒答，后端381项回归通过。

- [测试题目与标准](500题测试数据.csv)
- [完整优化报告](500题测试与优化总报告.md)
- [最终逐题评分](round-3/逐题评分.csv)
- [最终原始回答](round-3/results.json)
- [正式测试资料](materials/01-项目档案-v1.md)：同目录另有PDF和TXT。

raw结果只包含虚构内容及本地记录UUID，不含账号密码、真实令牌或会话Cookie。首个并行尝试的99条服务失败保存在round-1；未达标完整轮次在round-2；达标轮次在round-3。评分模型与作答模型同源，结果属于已知语料回归，未经过独立人工评分或陌生资料盲测。

## 从新环境复现

先按根目录README启动V2并准备模型与DeepSeek密钥，在H5创建专用测试账号，将账号仅通过当前进程环境变量传给评测。不要使用真实资料。

```powershell
$env:AIKNOWLEDGE_EVAL_EMAIL = '你创建的专用测试账号邮箱'
# 使用交互读取密码，避免将密码写进脚本或提交版本库
$credential = Get-Credential -UserName $env:AIKNOWLEDGE_EVAL_EMAIL
$env:AIKNOWLEDGE_EVAL_PASSWORD = $credential.GetNetworkCredential().Password
& .\aiknowledge\.venv\Scripts\python.exe -u eval/v2/synthetic_500.py round-1
& .\aiknowledge\.venv\Scripts\python.exe -u eval/v2/synthetic_500_judge.py round-1
& .\aiknowledge\.venv\Scripts\python.exe eval/v2/synthetic_500_report.py round-1
Remove-Item Env:AIKNOWLEDGE_EVAL_PASSWORD
```

脚本会创建三个独立私密空间并导入materials，临时使用PRO演示配额，结束恢复初始套餐；没有支付调用。问答及评分会调用已配置的第三方模型并产生用量。题库与结果写入忽略的output目录；不要编辑冻结题库以改变分数。若本地已有历史state，它属于原测试账号，应在独立克隆目录复现或使用匹配的专用账号，不混用账号状态。

50/150题脚本保留为历史本地实验工具，依赖未纳入Git的当时output，正式可复现入口以上述500题脚本为准。题库摘要按UTF-8、LF规范化文本计算SHA-256。

若Docker CLI未加入PATH，可设置 `AIKNOWLEDGE_EVAL_DOCKER` 为docker.exe绝对路径后再生成报告。
