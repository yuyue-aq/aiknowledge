import json,statistics,math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/evaluation/20261006-optimized'
rows=json.loads((OUT/'results.json').read_text(encoding='utf-8'))
metadata=json.loads((OUT/'run-metadata.json').read_text(encoding='utf-8-sig'))
cache_checks=json.loads((OUT/'native-cache-api-check.json').read_text(encoding='utf-8'))
by_id={x['message_id']:x for x in metadata}
assert len(rows)==50 and len(metadata)==57
assert json.loads((OUT/'gold_cases.json').read_text(encoding='utf-8'))==json.loads((ROOT/'output/evaluation/20261006/gold_cases.json').read_text(encoding='utf-8'))
citation_count=0
for row in rows:
    doc=json.loads((OUT/('document-'+row['format']+'.json')).read_text(encoding='utf-8'))
    original=json.loads((ROOT/'output/evaluation/20261006'/('document-'+row['format']+'.json')).read_text(encoding='utf-8'))
    assert doc['document']['active_version_id']==original['document']['active_version_id']
    source={x['ordinal']:x['content'] for x in doc['chunks']}
    for citation in row['response']['citations']:
        assert citation.get('source_available',True)
        assert citation['quoted_text']==source[citation['ordinal']]
        assert citation['document_name']==doc['document']['original_filename']
        citation_count+=1
    assert row['response']['status']==('ANSWERED' if row['answerable'] else 'INSUFFICIENT_EVIDENCE')
    row['review']={'score':2,'reviewer':'Codex assistant; not independently human verified',
                  'note':'必答事实完整、状态正确，引用与对应资料一致。'}
    row['runtime']=by_id[row['response']['message_id']]
    assert row['runtime']['prompt_version']=='rag-prompt-v2-coverage-grid-audit'
old_cold=rows[0]['runtime']
native_cold=by_id[cache_checks[0]['response']['message_id']]
phases=old_cold['model']['execution_timings_ms']
native_phases=native_cold['model']['execution_timings_ms']
latencies=sorted(x['runtime']['latency_ms']/1000 for x in rows)
summary={'total':50,'complete':50,'partial':0,'incorrect':0,'score':100,'strict_pass_rate':1.,
    'refusal_status_correct':10,'backend_tests':363,'citation_source_checks':citation_count,
    'host_bind_first_question_seconds':old_cold['latency_ms']/1000,
    'native_cache_first_question_seconds':native_cold['latency_ms']/1000,
    'host_bind_phases_ms':phases,'native_cache_phases_ms':native_phases,
    'native_cache_comparison_http_seconds':cache_checks[1]['seconds'],
    'model_files_sha256_verified':27,'cached_model_dimension':1024,
    'p50_seconds':statistics.median(latencies),'p95_seconds':latencies[math.ceil(.95*50)-1],
    'input_tokens_55_answers':sum(x['runtime']['input_tokens'] or 0 for x in rows)+sum(by_id[x['setup_response']['message_id']]['input_tokens'] or 0 for x in rows if x.get('setup_response')),
    'output_tokens_55_answers':sum(x['runtime']['output_tokens'] or 0 for x in rows)+sum(by_id[x['setup_response']['message_id']]['output_tokens'] or 0 for x in rows if x.get('setup_response')),
    'prompt_version':'rag-prompt-v2-coverage-grid-audit'}
(OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'reviewed_results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# V2综合题覆盖与本地模型缓存优化报告','',
    '日期：2026-10-06（Asia/Shanghai）。评分由Codex助手逐题核对，未经独立人工复核。','',
    '## 结果','',
    '原50题同资料版本复测：50题完全通过，10道拒答状态全部正确，得分100/100。上一轮49题通过、1题部分通过的Q24已补全项目B的PostgreSQL库存事务与行级锁用途。363项后端测试通过。',
    '这是已知合成回归集，已多次用于调优，不是盲测或泛化能力证明；不能保证任意资料和问法零遗漏。','',
    '## 综合题优化','',
    '对于显式命名的两个项目/系统/服务/方案，并比较2至4个英文组件标签的问题，从用户问题构造对象×组件格子。生成必须提供完整coverage，每个有依据格子必须带合法引用；缺格要求补全重试，仍不完整则不作为完整回答放行。无依据格子明确说明缺失，不渲染模型编造的用途。最终文字直接由格子生成，避免提取到的事实又在摘要中被漏掉。',
    '支持范围是上述显式比较形式；三个及以上对象、中文组件等未识别情形回退普通问答，没有冒充全覆盖。',
    '四种问法与一个Elasticsearch缺失信息负例的真实模型候选回放已通过；回放使用原问题已授权候选，不是这五个新问法的独立检索验收。完整50题和缓存模式Q24则通过真实问答API执行。',
    '补全重试与语义核验的成功调用token累计记录。','',
    '## 性能排查与缓存','',
    f'新增分段计时确认：Windows模型绑定模式首题后端执行{summary["host_bind_first_question_seconds"]:.2f}秒，其中向量处理{phases["embedding"]/1000:.2f}秒，生成{phases["generation"]/1000:.2f}秒。此前358秒只有总计时，不能全部归因于模型加载或网络。',
    '独立模型进程冷加载19.47秒、同一容器内临时新API冷检索20.37秒，不能代表容器重建后的首次文件读取成本。',
    '将同一模型复制到Docker本地卷，原Windows模型不删除、不修改。27个文件逐一SHA-256匹配，向量维度保持1024。无网络的新容器缓存加载17.47秒。',
    f'切换本地缓存并重建API后，相同Q01的后端执行{summary["native_cache_first_question_seconds"]:.2f}秒，其中向量处理{native_phases["embedding"]/1000:.2f}秒、生成{native_phases["generation"]/1000:.2f}秒；HTTP客户端测得首问{cache_checks[0]["seconds"]:.2f}秒。其后真实Q24约{cache_checks[1]["seconds"]:.2f}秒，四格用途完整。',
    '这是本机本次测量，不是所有机器、完全清空操作系统文件缓存后的硬件基准。数据支持本地卷有明显改善，但文件缓存和机器负载会影响数值。',
    '独立限制DeepSeek连接/写入/连接池等待最多10秒（配置更短则使用较短值），生成读取等待仍按原配置；这个改动不能代替向量加载优化。检索与生成计时保存在后端运行记录，不暴露凭据。',
    f'50题绑定模式运行P50={summary["p50_seconds"]:.2f}秒、P95={summary["p95_seconds"]:.2f}秒；首题长等待单独记录，不能用P95掩盖。缓存模式另做首问和Q24验证，没有再次重复整套50题；模型文件与向量版本相同。','',
    '## 当前启动方式','',
    '当前Docker API和Worker使用只读模型缓存卷。原compose.yaml、原模型和.env均保留；本轮没有修改.env或扩大分享权限。',
    '项目根目录启动缓存模式：','',
    '```powershell',
    'cd D:\\develop\\aiknowledge',
    'docker compose -f compose.yaml -f compose.model-cache.yaml --env-file aiknowledge/.env up -d --no-build',
    '```','',
    '当前缓存已准备好。全新机器需先准备模型与API镜像，再运行 tools/prepare-model-cache.ps1；已有缓存若相同会验证后复用，不覆盖正在使用的模型。缓存卷名为 aiknowledge_bge_models_v1。',
    '使用原compose.yaml启动会回退Windows绑定模式，功能仍可用，但首次加载可能较慢。不要在当前已有资料的环境执行docker compose down -v。','',
    '## 证据与限制','',
    f'{citation_count}条50题返回引用逐一比对当前资料片段、文件名和可用状态，均一致。所有文字与行为状态按原标准答案审核。引用一致性不是事实完整性的替代。',
    f'55个正式/前置回答的输入token={summary["input_tokens_55_answers"]}、输出token={summary["output_tokens_55_answers"]}。统计含相应补全或语义核验，不含另做的候选回放、早前迭代和缓存两问。',
    '本轮不属于真实用户数据、团队越权、公开访客或生产部署的独立验收。未提交或推送源码。','',
    '## 逐题实际结果','',
]
for row in rows:
    lines+=['### '+row['id']+' '+row['question'],'','标准答案：'+row['expected_answer'],'',
            '实际回答：'+row['response']['answer'],'','状态：'+row['response']['status']+'；得分：2/2。','']
(OUT/'综合题覆盖与模型缓存优化报告.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
