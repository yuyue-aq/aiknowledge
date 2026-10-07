import hashlib
import json
from pathlib import Path


def test_gold_fixture_has_fifty_frozen_cases_and_exact_source_evidence():
    root = Path(__file__).resolve().parents[2] / 'eval' / 'v2'
    dataset = json.loads((root / 'gold_cases.json').read_text(encoding='utf-8'))
    cases = dataset['cases']
    assert len(cases) == 50
    assert len({item['id'] for item in cases}) == 50
    assert len({item['question'] for item in cases}) == 50
    assert sum(item['split'] == 'tune' for item in cases) == 35
    assert sum(item['split'] == 'holdout' for item in cases) == 15
    for case in cases:
        assert case['expected_behavior'] in {'ANSWERED', 'INSUFFICIENT_EVIDENCE', 'OUT_OF_SCOPE', 'CONFLICT'}
        assert case['expected_answer']
        assert 'actual_answer' not in case
        for ref in case['evidence_templates']:
            text = (root / 'sources' / ref['filename']).read_text(encoding='utf-8')
            evidence = text[ref['char_start']:ref['char_end']]
            assert evidence == ref['text']
            assert hashlib.sha256(evidence.encode('utf-8')).hexdigest() == ref['text_hash']
        if case['expected_behavior'] == 'ANSWERED':
            assert case['answerable'] is True
            assert case['evidence_templates']
