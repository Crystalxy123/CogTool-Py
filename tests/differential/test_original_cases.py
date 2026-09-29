"""Real original-run gate. Missing originals are skipped, never manufactured."""
from pathlib import Path
import json

import pytest

from cogtool_py.comparison import compare_results

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.differential
@pytest.mark.parametrize('case_id', ['single_click', 'text_entry', 'two_page_wait'])
def test_original_reference_case(case_id: str):
    manifest = ROOT / 'validation/original/cases' / case_id / 'manifest.json'
    if not manifest.exists():
        pytest.skip(f'{case_id}: real original evidence unavailable; differential test not executed')
    metadata = json.loads(manifest.read_text(encoding='utf-8'))
    assert metadata['evidence_kind'] == 'original_run', 'Synthetic evidence cannot enter original validation'
    result = ROOT / 'validation/python' / case_id / 'result.json'
    assert result.exists(), f'Missing saved Python result: {result}'
    comparison = compare_results(result, manifest)
    assert comparison['comparison_status'] == 'matched_reported_fields', comparison['differences']
    assert comparison['equivalence_claim'] is False
