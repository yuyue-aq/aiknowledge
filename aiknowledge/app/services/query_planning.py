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
        planned=tuple(dict.fromkeys(x.strip() for x in values if x.strip()!=question.strip()))
        protected=_protected_query_terms(question)
        if planned and any(any(term.casefold() not in query.casefold() for term in protected) for query in planned):return ()
        return planned
    except (ValueError,TypeError,KeyError):return ()


def _protected_query_terms(question: str) -> tuple[str, ...]:
    """Return literal constraints that generated subqueries must not drop.

    Dates, numeric limits, mixed identifiers, and negated clauses stay
    verbatim. Numbered-list labels (such as ``1)``) are structure, not query
    constraints, and therefore are excluded unless they are part of a larger
    value such as ``1.2`` or ``PRJ-A17``.
    """
    item_labels={
        match.group(1)
        for match in re.finditer(r'(?:^|[：:；;\n])\s*(\d{1,2})\s*[)）.、]',question)
    }
    protected=[]
    for match in re.finditer(r'(?<![A-Za-z0-9])[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*\d[A-Za-z0-9_-]*',question):
        value=match.group(0)
        if value.casefold() not in {item.casefold() for item in item_labels}:
            protected.append(value)
    for match in re.finditer(r'\d+(?:[./:-]\d+)*(?:年|月|日|天|周|个月|小时|分钟|秒|%|％|人|个|项|条)?',question):
        value=match.group(0)
        if value not in item_labels:
            protected.append(value)
    for match in re.finditer(r'(?:不得|不能|不可|禁止|不|未|无|没有|没(?:有)?|非)[^，,。；;！？!?\n]{0,16}',question):
        value=match.group(0).strip()
        if value:
            protected.append(value)
    return tuple(dict.fromkeys(protected))
