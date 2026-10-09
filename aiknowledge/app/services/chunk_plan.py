"""Deterministic source-preserving alternatives, shared by preview and ingestion."""
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from app.services.token_budget import TokenBudget


@dataclass(frozen=True,slots=True)
class ChunkConfig:
    strategy: str='structure'
    max_tokens: int=512
    overlap_characters: int=240

    def __post_init__(self):
        if self.strategy not in ('legacy','structure'):
            raise ValueError('不支持的分块策略。')
        if type(self.max_tokens) is not int or not 16<=self.max_tokens<=512:
            raise ValueError('分块token预算必须为16—512的整数。')
        if type(self.overlap_characters) is not int or not 0<=self.overlap_characters<=240:
            raise ValueError('重叠字符必须为0—240的整数。')

    def _values(self):
        return {'strategy':self.strategy,'strategy_version':'source-paragraph-token-v1',
            'max_tokens_including_special':self.max_tokens,'overlap_characters':self.overlap_characters,
            'max_characters':1800,'preserve_source_offsets':True,'overlap_limit':'half_chunk',
            'token_count_strategy':'model_tokenizer'}

    @property
    def fingerprint(self):
        return sha256(json.dumps(self._values(),sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def snapshot(self):return {**self._values(),'configuration_fingerprint':self.fingerprint}

    @classmethod
    def from_dict(cls,value):
        if value.get('strategy_version')!='source-paragraph-token-v1':
            raise ValueError('分块配置版本不支持。')
        result=cls(strategy=value.get('strategy'),max_tokens=value.get('max_tokens_including_special'),
            overlap_characters=value.get('overlap_characters'))
        if value!=result.snapshot():raise ValueError('分块配置指纹或字段无效。')
        return result


@dataclass(frozen=True,slots=True)
class PlannedChunk:
    ordinal: int
    content: str
    heading_path: tuple[str,...]
    page_number: int|None
    source_block_id: str
    char_start: int
    char_end: int
    content_hash: str
    token_count: int


def _paragraph_spans(text):
    boundaries={0,len(text)}
    boundaries.update(m.end() for m in re.finditer(r'\n[ \t]*\n+',text))
    # Explicit structure only. Do not guess a project from prose or merge blocks.
    boundaries.update(m.start() for m in re.finditer(r'(?m)^(?:#{1,6}[ \t]+[^\n]+|\d{1,2}[ \t]+[^\n。！？；]{1,40}|第[一二三四五六七八九十\d]+[章节][^\n]{0,40})$',text))
    result=[];start=0
    for end in sorted(boundaries):
        if end>start and text[start:end].strip():result.append((start,end));start=end
    if start<len(text):
        if result:result[-1]=(result[-1][0],len(text))
    return result


def plan_chunks(document,budget,config):
    if config.max_tokens>budget.capacity:raise ValueError('分块预算超过当前向量模型容量。')
    if sum(len(b.text) for b in document.blocks)>2_000_000:raise ValueError('资料正文超过本阶段分块处理上限。')
    limited=TokenBudget(budget.tokenizer,capacity=config.max_tokens)
    result=[]
    for block in document.blocks:
        spans=_paragraph_spans(block.text) if config.strategy=='structure' else [(0,len(block.text))]
        for start,end in spans:
            for part in limited.split(block.text[start:end],overlap_characters=config.overlap_characters):
                result.append(PlannedChunk(len(result)+1,part.content,block.heading_path,block.page_number,
                    f'block-{block.ordinal}',start+part.char_start,start+part.char_end,
                    sha256(part.content.encode()).hexdigest(),part.token_count))
                if len(result)>10000:raise ValueError('分块数量超过本阶段处理上限。')
    if not result:raise ValueError('资料没有可分块的正文。')
    return tuple(result)
