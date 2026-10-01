"""Build five self-contained offline prototypes from canonical shared sources."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
DEFINITIONS = [
('01-核心业务.html','核心业务','从资料管理到检索证据，再到可信问答。',[
('spaces','知识空间','选择空间或创建演示空间','空间'),('docs','资料管理','上传、状态、版本与删除','资料'),('detail','资料详情','活动版本、片段与更新','资料'),('retrieval','独立检索','输入问题，查看 Top K 证据','问答'),('chat','可信问答','回答、引用与纠错入口','问答'),('evidence','来源核验','查看原文片段及页码','问答')]),
('02-评测与复测.html','评测与复测','保存测试题、选取相关证据，人工评分并比较两次运行。',[
('cases','测试题管理','管理问题、标准答案与相关证据','评测'),('edit','编辑测试题','填写答案及评测范围','评测'),('select','选择相关证据','关联文档与片段','评测'),('run','运行评测','进度与运行快照','评测'),('grade','人工评分','判断检索与回答表现','评测'),('compare','复测对比','比较同一题集的两次结果','评测')]),
('03-公开分享.html','公开分享','拥有者管理开放主题；访客在当前有效范围内提问。',[
('categories','开放分类','逐项控制公开范围','空间'),('share','分享链接','链接、状态与撤销','空间'),('public-start','访客提问','查看开放主题并提问',''),('public-answer','访客回答','展示回答与主题范围',''),('public-insufficient','依据不足','说明限制并引导换问法',''),('public-expired','链接失效','撤销、过期或无开放主题','')]),
('04-反馈与异常状态.html','反馈与异常状态','覆盖问题反馈、修复复测，以及核心流程中的可恢复状态。',[
('feedback-form','提交反馈','定位回答问题并补充说明','反馈'),('feedback-list','反馈列表','查看状态与处理入口','反馈'),('repair','修复与复测','更新资料后重跑相关问题','反馈'),('empty','空状态','无资料或无相关结果','资料'),('upload-fail','上传失败','失败原因及重试入口','资料'),('model-fail','生成失败','保留问题并允许重试','问答'),('scope-change','范围发生变化','停止旧范围回答并提示重问','问答'),('delete','删除确认','明确影响与取消操作','资料'),('pending','资料处理中','等待可检索状态','资料')]),
('05-后续扩展.html','后续扩展','P1 / P2 概念页面，仅用于明确后续能力与产品位置。',[
('chunk','P1 · 分块策略','调整分块并预览片段','资料'),('hybrid','P1 · 混合检索','向量与 BM25 对比','问答'),('rerank','P1 · 重排对比','查看排序前后的证据','问答'),('rewrite','P2 · 问题改写','查看原问题与改写建议','问答'),('publish','P2 · 公开稿审核','审核后形成公开内容','空间'),('feedback-case','P2 · 反馈转回归题','将反馈关联到测试题','反馈')])]
groups = [dict(index=i,file=f,title=t,description=d,scenes=[dict(type=k,title=n,desc=x,nav=v) for k,n,x,v in rows]) for i,(f,t,d,rows) in enumerate(DEFINITIONS)]
css=(ROOT/'assets/prototype.css').read_text(encoding='utf-8')
js=(ROOT/'assets/prototype.js').read_text(encoding='utf-8')
# Submit buttons retain native form submission; keep all toast feedback in the modal top layer.
js=js.replace('type="button" class="btn ${variant}"', 'type="${action.startsWith(\'submit-\')?\'submit\':\'button\'}" class="btn ${variant}"')
js=js.replace("const t=$('#toast');t.textContent", "const t=$('#toast');(dialog.open?dialog:document.body).append(t);t.textContent")
js=js.replace('form.topk.value',"form.elements.namedItem('topk').value")
js=js.replace("'go-retrieval','ghost','class=\"active\"'", "'go-retrieval','ghost active'")
js=js.replace('相关片段 · 5 条','相关片段 · 3 条')
js=js.replace('保存评分并下一题','保存演示评分')
js=js.replace("go(a==='delete'?'empty':'public-expired')", "if(a==='delete'){go('docs');$('tbody tr',dialog)?.remove();$('.counts span',dialog).textContent='显示 2 份演示资料';$('.toolbar .pill',dialog).textContent='全部资料 · 2'}else go('public-expired')")
# A single named handler also owns literal buttons, so static review can resolve actions.
js=js.replace("document.addEventListener('click',e=>{", "function handlePrototypeClick(e){e.stopPropagation();")
js=js.replace("});\n\ndocument.addEventListener('submit'", "}\ndocument.addEventListener('click',handlePrototypeClick);\n\ndocument.addEventListener('submit'")
import re
js=re.sub(r"\}\);\s*(?=document.addEventListener\('submit')", "}\ndocument.addEventListener('click',handlePrototypeClick);\n",js)
js=re.sub(r'<button(?![^>]*onclick=)', '<button onclick="handlePrototypeClick(event)"', js)
# Gallery is a non-interactive miniature. Remove duplicate IDs and label targets there.
js=js.replace('${renderScene(s)}</div></div></div>', '${renderScene(s).replace(/\\s(?:id|for)="[^"]*"/g,\'\')}</div></div></div>')
(ROOT/'assets/prototype.js').write_text(js,encoding='utf-8')
def data(value): return json.dumps(value,ensure_ascii=False).replace('<','\\u003c')
for g in groups:
    html=f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#0D213D"><title>{g['title']} · 知溯 V2 原型</title><style>{css}</style></head>
<body><header class="review-header"><div class="review-brand"><span class="brand-logo">溯</span><strong>知溯 <small>V2 · HTML 原型</small></strong></div><span class="pill">沿用 V1 · 极昼蓝</span></header>
<nav class="review-nav" id="review-nav" aria-label="原型分组"></nav><main class="review-main"><div class="review-heading"><div><div class="eyebrow">PROTOTYPE / {g['index']+1:02d}</div><h1>{g['title']}</h1><p>{g['description']}</p></div><span class="pill">{len(g['scenes'])} 个场景</span></div>
<div class="notice"><div><strong>离线交互演示</strong> · 全部资料、回答、指标和链接均为合成样例。点击“查看”体验页面，支持桌面 / 手机预览；不连接真实模型或数据库。</div></div><section class="gallery" id="gallery" aria-label="页面原型"></section><p class="review-footer">宽屏一行三列 · 小屏自动排列 · 每个 HTML 可独立打开。后续扩展页面标注 P1 / P2。</p></main>
<dialog class="preview-dialog" id="preview" aria-labelledby="preview-title"><div class="preview-bar"><strong id="preview-title"></strong><div class="row"><button class="btn outline small" type="button" data-device="desktop" aria-pressed="true">桌面</button><button class="btn outline small" type="button" data-device="phone" aria-pressed="false">手机</button><button class="btn ghost small" type="button" id="close-preview" aria-label="关闭预览">关闭 ×</button></div></div><div class="preview-body" id="preview-content"></div></dialog>
<dialog class="confirm-dialog" id="confirm" aria-labelledby="confirm-title" aria-describedby="confirm-text"><h2 id="confirm-title"></h2><p id="confirm-text"></p><div class="row"><button class="btn outline" type="button" id="confirm-no">取消</button><button class="btn" type="button" id="confirm-yes">确认演示操作</button></div></dialog><div id="toast" class="toast hidden" role="status" aria-live="polite"></div>
<script>const GROUP={data(g)};const GROUPS={data(groups)};const ALL_SCENES={data([s for x in groups for s in x['scenes']])};</script><script>{js}</script></body></html>'''
    # Confirmation callbacks are assigned by confirmAction before showing the modal.
    html=re.sub(r'<button(?![^>]*onclick=)', '<button onclick="handlePrototypeClick(event)"',html)
    (ROOT/g['file']).write_text(html,encoding='utf-8')
print(f'Generated {len(groups)} standalone HTML files; {sum(len(g["scenes"]) for g in groups)} scenes.')
