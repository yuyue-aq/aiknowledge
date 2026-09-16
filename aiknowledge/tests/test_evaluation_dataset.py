from __future__ import annotations

import json
from pathlib import Path


def test_mvp_evaluation_manifest_has_twelve_cases_and_required_boundary_classes() -> None:
    manifest_path = Path(__file__).parents[2] / "eval" / "mvp_eval_set.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest["cases"]

    assert manifest["version"] == "mvp-eval-v1"
    assert len(cases) == 12
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["scope"] for case in cases} == {"OWNER", "PUBLIC", "OUT_OF_SCOPE"}
    tags = {tag for case in cases for tag in case["tags"]}
    assert {"citation", "follow-up", "private-canary", "verbatim-recovery"} <= tags
    assert all(case["question"].strip() for case in cases)
    assert all(case["expected_behavior"].strip() for case in cases)
