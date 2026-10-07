"""Coverage contract for explicitly named object/component comparisons."""
import re


def comparison_cells(question: str) -> tuple[tuple[str,str], ...]:
    if not any(word in question for word in ('分别','各自','比较','对比')):return ()
    match=re.search(r'(项目|系统|服务|方案)\s*([A-Za-z][A-Za-z0-9_-]*)\s*(?:与|和|、|及)\s*(项目|系统|服务|方案)?\s*([A-Za-z][A-Za-z0-9_-]*)',question)
    if not match:return ()
    label,first,second_label,second=match.groups()
    if re.match(r'\s*[与和、及]\s*(?:项目|系统|服务|方案)?\s*[A-Za-z]',question[match.end():]):return ()
    if len(re.findall(r'(?:项目|系统|服务|方案)\s*[A-Za-z][A-Za-z0-9_-]*',question))>2:return ()
    if first==second:return ()
    aspects=list(dict.fromkeys(word for word in re.findall(r'[A-Za-z][A-Za-z0-9_.+#-]*',question) if word not in (first,second) and len(word)>1))
    if not 2<=len(aspects)<=4:return ()
    cells=[]
    for obj_id,obj_label in ((first,label),(second,second_label or label)):
        explicit=re.search(r'(?:'+obj_label+r')?'+re.escape(obj_id)+r'\s*(?:只|仅)(?:解释|说明|列出|比较|讨论)([^；;。？！\n]*)',question)
        requested=aspects if explicit is None else [x for x in aspects if x in re.findall(r'[A-Za-z][A-Za-z0-9_.+#-]*',explicit.group(1))]
        for aspect in requested:
            excluded=re.search(r'(?:不要|禁止|不)(?:增加|包含|列出|回答|介绍|讨论)\s*(?:'+obj_label+r')?'+re.escape(obj_id)+r'(?:的|/)?\s*'+re.escape(aspect),question)
            if excluded is None:cells.append((obj_label+obj_id,aspect))
    return tuple(cells)


def render_coverage(rows,required,allowed_aliases):
    if not isinstance(rows,list) or len(rows)!=len(required):return None
    by_key={}
    for row in rows:
        if not isinstance(row,dict):return None
        key=(row.get('object'),row.get('aspect'))
        if key not in required or key in by_key or not isinstance(row.get('available'),bool):return None
        if row['available']:
            aliases=row.get('citation_ids')
            if not isinstance(row.get('answer'),str) or not row['answer'].strip():return None
            if not isinstance(aliases,list) or not aliases or not all(isinstance(alias,str) and alias in allowed_aliases for alias in aliases):return None
        by_key[key]=row
    if set(by_key)!=set(required):return None
    answer=[]
    aliases=[]
    for obj,aspect in required:
        row=by_key[obj,aspect]
        value=row['answer'].strip() if row['available'] else '资料未提供该项信息。'
        answer.append(f'{obj} / {aspect}：{value}')
        if row['available']:aliases.extend(row['citation_ids'])
    return '\n'.join(answer),list(dict.fromkeys(aliases))
