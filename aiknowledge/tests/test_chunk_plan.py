import hashlib
import pytest
from app.domain.documents import DocumentBlock,DocumentFormat,ParsedDocument
from app.services.token_budget import TokenBudget
from app.services.chunk_plan import ChunkConfig,plan_chunks

def tokenizer(text,**kwargs):return {'input_ids':list(range(len(text)+2))}
def document(text):return ParsedDocument(filename='验证.md',format=DocumentFormat.MARKDOWN,
    blocks=(DocumentBlock(text=text,heading_path=('项目甲',),ordinal=3,page_number=2),))

def test_structure_never_merges_paragraphs_and_preserves_exact_source():
    source='第一段事实。\n\n第二段事实。\n## 下一节\n第三段事实。'
    result=plan_chunks(document(source),TokenBudget(tokenizer,capacity=64),ChunkConfig(strategy='structure',max_tokens=64,overlap_characters=0))
    assert len(result)>=3 and ''.join(x.content for x in result)==source
    assert all(source[x.char_start:x.char_end]==x.content for x in result)
    assert all(x.source_block_id=='block-3' and x.page_number==2 and x.heading_path==('项目甲',) for x in result)
    assert all(x.content_hash==hashlib.sha256(x.content.encode()).hexdigest() for x in result)

def test_legacy_matches_existing_token_splitter():
    source='资料甲。'*15
    budget=TokenBudget(tokenizer,capacity=32)
    expected=budget.split(source,overlap_characters=8)
    got=plan_chunks(document(source),budget,ChunkConfig(strategy='legacy',max_tokens=32,overlap_characters=8))
    assert [(x.content,x.char_start,x.char_end,x.token_count) for x in got]==[(x.content,x.char_start,x.char_end,x.token_count) for x in expected]

def test_long_paragraph_is_complete_with_budget_and_overlap():
    source='前言。'+'长段落事实'*40+'最后证据。'
    got=plan_chunks(document(source),TokenBudget(tokenizer,capacity=32),ChunkConfig(strategy='structure',max_tokens=24,overlap_characters=8))
    covered=set()
    for x in got:
        assert x.token_count<=24 and source[x.char_start:x.char_end]==x.content
        covered.update(range(x.char_start,x.char_end))
    assert covered==set(range(len(source))) and got[-1].char_end==len(source)

def test_blocks_and_project_headings_remain_separate():
    parsed=ParsedDocument(filename='项目.md',format=DocumentFormat.MARKDOWN,blocks=(
        DocumentBlock(text='甲的事实',heading_path=('甲',),ordinal=1),
        DocumentBlock(text='乙的事实',heading_path=('乙',),ordinal=2)))
    got=plan_chunks(parsed,TokenBudget(tokenizer,capacity=64),ChunkConfig(max_tokens=64))
    assert [x.heading_path for x in got]==[('甲',),('乙',)]
    assert [x.ordinal for x in got]==[1,2]

@pytest.mark.parametrize('kwargs',[{'strategy':'unknown'},{'max_tokens':True},{'max_tokens':513},{'max_tokens':0},{'overlap_characters':-1},{'overlap_characters':241}])
def test_invalid_configuration_rejected(kwargs):
    with pytest.raises(ValueError):ChunkConfig(**kwargs)

def test_config_fingerprint_stable_and_changes_with_parameters():
    a=ChunkConfig();b=ChunkConfig(overlap_characters=0)
    assert a.fingerprint==ChunkConfig.from_dict(a.snapshot()).fingerprint
    assert a.fingerprint!=b.fingerprint

def test_model_capacity_not_silently_clamped_and_empty_not_indexable():
    with pytest.raises(ValueError):plan_chunks(document('内容'),TokenBudget(tokenizer,capacity=32),ChunkConfig(max_tokens=64))
    with pytest.raises(ValueError):plan_chunks(document('  '),TokenBudget(tokenizer,capacity=64),ChunkConfig(max_tokens=64))
