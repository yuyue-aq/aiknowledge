"""Bounded retrieval planning; subqueries never determine access scope."""
from dataclasses import dataclass,field
import json
import re
from app.domain.rag import Usage


@dataclass(frozen=True)
class QueryPlan:
    queries: tuple[str,...] = ()
    usage: Usage = field(default_factory=Usage)


def complex_question(question: str) -> bool:
    numbered = re.findall(r'(?:^|[\n：:；;])\s*\d{1,2}(?:[）)、]|\.(?!\d))', question)
    return len(numbered)>1 or sum(question.count(x) for x in ('？','?'))>1 or any(x in question for x in
        ('分别','各自','比较','对比','两个','多个','两种','区分','哪些','完整','先后','起止','自然月','顺序','逐项','以及','且不'))


def parse_queries(content: str,question: str) -> tuple[str,...]:
    try:
        values=json.loads(content)['queries']
        if not isinstance(values,list) or len(values)>4:return ()
        if any(not isinstance(x,str) or not 1<=len(x.strip())<=200 for x in values):return ()
        return tuple(dict.fromkeys(x.strip() for x in values if x.strip()!=question.strip()))
    except (ValueError,TypeError,KeyError):return ()
