async (page) => {
 const id=n=>'00000000-0000-0000-0000-'+String(n).padStart(12,'0'), now='2026-10-01T00:00:00Z';
 const hash=await page.evaluate(async()=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode('试用期为14天。')))).map(x=>x.toString(16).padStart(2,'0')).join(''));
 const doc={id:id(12),space_id:id(2),original_filename:'产品说明.txt',mime_type:'text/plain',size_bytes:21,status:'READY',active_version_id:id(13),is_enabled:true,category_id:null,created_at:now,updated_at:now};
 const chunk={rank:1,chunk_id:id(11),document_id:id(12),document_version_id:id(13),document_name:doc.original_filename,content:'试用期为14天。',source_block_id:'block-1',char_start:0,char_end:8,content_hash:hash,ordinal:1,score:.91,token_count:12,page_number:null};
 const q={id:id(20),space_id:id(2),question:'试用期多长？',expected_answer:'14天',expected_document_ids:[id(12)],scope:'OWNER',category_ids:[],answerable:true,expected_behavior:'ANSWERED',evidence_refs:[],created_at:now};
 const run=n=>({id:id(n),space_id:id(2),status:'COMPLETED',created_at:now,completed_at:now,progress_total:1,progress_completed:1,retrieval_config_snapshot:{eval_cases:[q],knowledge_manifest:{digest:'synthetic-same-fixture'}},failure_code:null});
 const result=n=>({id:id(n+30),eval_case_id:q.id,answer_status:'ANSWERED',answer:n===30?'7天':'14天',citation_count:1,out_of_scope_violation:false,reviewer_score:n===30?0:null,reviewer_note:null,retrieval_metrics:{document_recall_at_k:1,evidence_recall_at_k:1}});
 const summary=score=>({total:1,answered:1,insufficient_evidence:0,out_of_scope:0,failed:0,citation_count:1,out_of_scope_violations:0,reviewed_correct:score===1?1:0,reviewed_partial:0,reviewed_incorrect:score===0?1:0,answered_rate:1,citation_rate:1,reviewed_accuracy:score,answer_accuracy:score,reviewed_coverage:score==null?0:1,document_recall_at_k:1,evidence_recall_at_k:1,document_hit_at_k:1,correct_refusal_rate:null});
 globalThis.v2UI={doc,chunk,cases:[q],runs:[run(31),run(30)],results:{[id(30)]:result(30),[id(31)]:result(31)},versions:[],polls:0,pendingRun:null,feedback:[],versionsForDocument:[{id:id(13),version_number:1,status:'READY',created_at:now}],categories:[{id:id(90),space_id:id(2),name:'产品说明',description:'公开说明',is_open:true,sort_order:0,created_at:now}],links:[],answerStatus:'ANSWERED',calls:[],screens:[]};
 await page.route('**/api/v1/**',async route=>{
   const f=globalThis.v2UI, request=route.request(), p=new URL(request.url()).pathname, method=request.method();
   f.calls.push({path:p,method});let data=null,status=200;
   if(p.endsWith('/__ui_control')) { if(method==='POST') Object.assign(f, request.postDataJSON()); data={mode:'synthetic_ui_only',cases:f.cases,runs:f.runs,results:f.results,calls:f.calls,feedback:f.feedback}; }
   else if(p.endsWith('/members')&&method==='GET') data=[];
   else if(p.endsWith('/usage')) data={space_id:id(2),plan:'FREE',documents_used:1,documents_remaining:19,members_used:1,members_remaining:0,questions_used_today:0,questions_remaining_today:100,limits:{documents:20,members:1,questions_per_day:100}};
   else if(p.endsWith('/public-analytics')) data={space_id:id(2),sessions:0,conversations:0,questions:0,unique_visitors:0,daily:[],period_start:now,period_end:now};
   else if(p.endsWith('/categories')&&method==='GET') data={items:f.categories};
   else if(p.includes('/categories/')&&method==='PATCH') {const c=f.categories.find(c=>c.id===p.split('/').pop());Object.assign(c,request.postDataJSON());data=c;}
   else if(p.endsWith('/share-links')&&method==='GET') data={items:f.links};
   else if(p.endsWith('/share-links')&&method==='POST') {const link={id:id(91),space_id:id(2),category_ids:request.postDataJSON().category_ids,status:'ACTIVE',created_at:now,revoked_at:null,expires_at:null,allowed_origins:[],visitor_question_limit:null};f.links.push(link);data={link,token:'synthetic-ui-token'};}
   else if(p.includes('/share-links/')&&method==='DELETE') {f.links=f.links.map(l=>({...l,status:'REVOKED',revoked_at:now}));data={};}
   else if(p.endsWith('/public/session')||p.endsWith('/public/space')) {status=f.publicExpired?403:200;data=f.publicExpired?{detail:'分享链接已失效'}:{name:'产品公开问答',description:'仅围绕开放分类回答。',categories:[{name:f.publicChanged?'最新公开分类':'产品说明',description:'公开使用说明'}]};}
   else if(p.endsWith('/public/conversations')&&method==='POST') data={id:id(80),created_at:now};
   else if(p.includes('/public/conversations/')&&p.endsWith('/messages')) {if(f.publicScopeChange){f.publicChanged=true;f.publicScopeChange=false;status=409;data={detail:'公开范围已变化，请重新提问',code:'SCOPE_CHANGED'};}else data={message_id:id(81),status:f.answerStatus,answer:f.answerStatus==='ANSWERED'?'试用期为14天。':'当前公开资料不足以回答。',model:'synthetic-ui-fixture'};}
   else if(p.endsWith('/versions')&&method==='POST'&&p.includes('/documents/')) { f.versionsForDocument.unshift({id:id(14),version_number:2,status:'PROCESSING',created_at:now}); f.versionPolls=0; data={document:f.doc,version_id:id(14),processing_enqueued:true}; status=202; }
   else if(p.includes('/owner/spaces/')&&p.includes('/documents/')) { if(f.versionsForDocument[0].status==='PROCESSING'&&++f.versionPolls>=2){f.versionsForDocument[0].status='READY';f.doc={...f.doc,active_version_id:id(14),original_filename:'更新说明.txt'};} data={document:f.doc,versions:f.versionsForDocument,chunks:[{...f.chunk,document_version_id:f.doc.active_version_id,document_name:f.doc.original_filename}]}; }
   else if(p.includes('/owner/')&&p.endsWith('/evidence')) data={items:[f.chunk],unavailable_chunk_ids:[],snapshot_available:true};
   else if(p.endsWith('/eval-cases')&&method==='GET') data={items:f.cases};
   else if(p.endsWith('/eval-cases')&&method==='POST'){data={...request.postDataJSON(),id:id(21),space_id:id(2),created_at:now};f.cases.push(data)}
   else if(p.endsWith('/eval-versions')&&method==='GET') data={items:f.versions};
   else if(p.endsWith('/eval-versions')&&method==='POST'){data={id:id(40),space_id:id(2),version_number:1,label:request.postDataJSON().label,cases:[...f.cases],created_at:now};f.versions.push(data)}
   else if(p.endsWith('/eval-runs/compare')) data={baseline:f.runs[1],candidate:f.runs[0],baseline_summary:summary(0),candidate_summary:summary(1),same_test_set:true,question_changes:[{eval_case_id:q.id,baseline_question:q.question,candidate_question:q.question,baseline_status:'ANSWERED',candidate_status:'ANSWERED',baseline_score:0,candidate_score:1,comparable:true}],delta:{answer_accuracy:1,document_recall_at_k:0}};
   else if(p.endsWith('/eval-runs/async')&&method==='POST'){data={...run(32),status:'PENDING',progress_completed:0};f.pendingRun=data;f.polls=0;status=202}
   else if(p.endsWith('/eval-runs')&&method==='GET') data={items:f.runs};
   else if(/\/eval-runs\/[^/]+$/.test(p)){const selected=p.split('/').pop();let r=f.runs.find(x=>x.id===selected);
     if(f.pendingRun?.id===selected){f.polls++;r={...f.pendingRun,status:f.polls<2?'RUNNING':'COMPLETED',progress_completed:f.polls<2?0:1};if(r.status==='COMPLETED'&&!f.runs.some(x=>x.id===r.id)){f.runs.unshift(r);f.results[r.id]=result(32)}}
     data={run:r,results:r.status==='COMPLETED'?[f.results[r.id]]:[],summary:summary(f.results[r.id]?.reviewer_score??null)}}
   else if(/\/eval-results\//.test(p)&&method==='PATCH'){const rid=p.split('/').pop();const record=Object.values(f.results).find(x=>x.id===rid);Object.assign(record,request.postDataJSON());data=record}
   else if(p.endsWith('/feedback')&&method==='GET') data={items:f.feedback};
   else if(p.endsWith('/feedback')&&method==='POST'){data={id:id(70),rating:request.postDataJSON().rating,reason:request.postDataJSON().reason,comment:request.postDataJSON().comment,question:q.question,original_answer:'7天',created_at:now,review_status:'PENDING'};f.feedback.push(data)}
   else if(p.endsWith('/documents')&&method==='GET') data={items:f.emptyDocuments?[]:[f.doc]};
   else if(p.endsWith('/owner/conversations')&&method==='GET') data=[];
   else if(p.endsWith('/owner/conversations')&&method==='POST') data={id:id(3),space_id:id(2),title:null,created_at:now,updated_at:now};
   else if(p.endsWith('/messages')&&method==='POST') data={message_id:id(50),status:f.answerStatus,answer:f.answerStatus==='ANSWERED'?'试用期为14天。':'当前资料不足以回答。',model:'synthetic-ui-fixture',citations:[{document_name:doc.original_filename,quoted_text:chunk.content,page_number:null,ordinal:1,score:.91,source_available:true}]};
   else return route.fallback();
   await route.fulfill({status,json:data});
 });
 return {mode:'synthetic_ui_only',ready:true};
}
