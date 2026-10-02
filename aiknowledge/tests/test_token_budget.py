import pytest

from app.domain.retrieval import RetrievalError
from app.services.token_budget import TokenBudget


class Tokenizer:
    def __call__(self, text, *, add_special_tokens, truncation):
        assert add_special_tokens is True
        assert truncation is False
        # Independent test tokenizer: each Chinese char consumes two tokens.
        return {'input_ids': [0] * (2 + sum(2 if ord(c) > 127 else 1 for c in text))}


def test_split_preserves_entire_text_including_tail_and_exact_offsets():
    budget = TokenBudget(Tokenizer(), capacity=12)
    original = '第一行\n第二行。 最后证据XYZ'
    parts = budget.split(original)
    assert ''.join(p.content for p in parts) == original
    assert all(budget.count(p.content) <= 12 for p in parts)
    assert all(original[p.char_start:p.char_end] == p.content for p in parts)
    assert parts[-1].char_end == len(original)
    assert ''.join(p.content for p in parts).endswith('XYZ')


def test_query_budget_counts_prefix_and_special_tokens():
    budget = TokenBudget(Tokenizer(), capacity=12)
    budget.validate_query('中文', prefix='QUERY:')
    with pytest.raises(RetrievalError) as exc:
        budget.validate_query('中文中文', prefix='QUERY:')
    assert exc.value.code == 'QUERY_TOKEN_LIMIT'
    assert exc.value.status_code == 422


def test_split_rejects_a_single_unencodable_character():
    with pytest.raises(ValueError):
        TokenBudget(Tokenizer(), capacity=3).split('汉')


def test_empty_text_produces_no_chunks():
    assert TokenBudget(Tokenizer()).split('  \n ') == []


def test_overlap_keeps_raw_offsets_budget_and_full_coverage_without_looping():
    original = '甲乙丙丁戊己庚辛壬癸。最后证据XYZ'
    parts = TokenBudget(Tokenizer(), capacity=12).split(original, overlap_characters=240)
    assert len(parts) < len(original)
    assert parts[0].char_start == 0
    assert parts[-1].char_end == len(original)
    assert all(original[p.char_start:p.char_end] == p.content for p in parts)
    assert all(p.token_count <= 12 for p in parts)
    assert all(left.char_start < right.char_start < left.char_end < right.char_end for left, right in zip(parts, parts[1:]))
