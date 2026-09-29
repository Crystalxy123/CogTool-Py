"""Independent synthetic tests for evidence validation, NOT CogTool reference runs."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from cogtool_py import UPSTREAM
from cogtool_py.comparison import EvidenceError, compare_results

pytestmark = pytest.mark.independent


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def seal(bundle: Path, role: str) -> None:
    manifest = json.loads((bundle / 'manifest.json').read_text())
    entry = manifest['files'][role]
    entry['sha256'] = hashlib.sha256((bundle / entry['path']).read_bytes()).hexdigest()
    write(bundle / 'manifest.json', manifest)


@pytest.fixture
def synthetic_bundle(tmp_path: Path) -> tuple[Path, Path]:
    """Every number/output here is explicitly artificial test data."""
    bundle = tmp_path / 'synthetic_evidence'
    bundle.mkdir()
    result = {
        'software_version': 'synthetic-test-only',
        'engine': {'name': 'klm_baseline', 'version': '0.1.0'},
        'upstream': UPSTREAM, 'input_sha256': '1' * 64,
        'parameters': {'test_duration_s': 0.5},
        'task_id': 'synthetic_task', 'predicted_time_s': 0.5,
        'initial_state': {'frame': 'test_frame', 'mouse': [0, 0]},
        'timing_boundary': 'SYNTHETIC test start to end',
        'steps': [{'op': 'click', 'origin': 'demonstration', 'demo_index': 0,
                   'target': 'test_button', 'frame': 'test_frame'}],
        'events': [{'op': 'click', 'start_s': 0.0, 'end_s': 0.5,
                    'resource': 'serial_baseline', 'step_index': 0}],
    }
    py_path = tmp_path / 'python.json'
    write(py_path, result)
    original = copy.deepcopy(result)
    original['engine'] = {'name': 'synthetic_original', 'version': 'not-a-real-run'}
    config = {key: result[key] for key in
              ('input_sha256', 'parameters', 'initial_state', 'task_id', 'timing_boundary')}
    runtime = {
        'source_commit': UPSTREAM['commit'], 'version': 'SYNTHETIC',
        'platform': 'SYNTHETIC', 'java_version': 'SYNTHETIC', 'lisp_version': 'SYNTHETIC',
        'build_method': 'Never executed; unit-test-only evidence mechanism fixture',
        'binary_sha256': '2' * 64, 'memory_image_sha256': '3' * 64,
    }
    contents = {
        'original_input': {'synthetic_only': True},
        'configuration': config, 'generated_steps': original['steps'],
        'raw_trace': 'SYNTHETIC NOT ORIGINAL COGTOOL OUTPUT',
        'run_instructions': 'SYNTHETIC test data created by pytest; no original was run',
        'runtime_identity': runtime, 'normalized_result': original,
    }
    files = {}
    for role, content in contents.items():
        path = bundle / (role + '.json')
        write(path, content)
        files[role] = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {'schema_version': '1.0', 'evidence_kind': 'synthetic_test',
                'case_id': 'synthetic_only', 'upstream': UPSTREAM,
                'input_sha256': result['input_sha256'], 'files': files}
    write(bundle / 'manifest.json', manifest)
    return py_path, bundle / 'manifest.json'


def test_matching_synthetic_fields_never_claim_original_equivalence(synthetic_bundle):
    report = compare_results(*synthetic_bundle)
    assert report['comparison_status'] == 'matched_reported_fields'
    assert report['evidence_kind'] == 'synthetic_test'
    assert report['original_validation_status'] == 'unverified'
    assert report['equivalence_claim'] is False
    assert report['provenance_authenticity'] == 'requires_human_audit'


def test_reports_time_and_step_resource_differences(synthetic_bundle):
    py_path, manifest_path = synthetic_bundle
    py = json.loads(py_path.read_text())
    py['predicted_time_s'] = 0.7
    py['steps'][0]['origin'] = 'automatic'
    py['events'][0]['resource'] = 'changed_resource'
    write(py_path, py)
    report = compare_results(py_path, manifest_path)
    assert report['comparison_status'] == 'different'
    assert {row['field'] for row in report['differences']} == {
        'predicted_time_s', 'steps[0].origin', 'events[0].resource'}
    assert report['differences'][0]['difference_s'] == pytest.approx(0.2)


@pytest.mark.parametrize('delta,expected', [(5e-10, 'matched_reported_fields'),
                                            (0.0005, 'different')])
def test_tolerance_is_float_roundoff_not_human_prediction_error(synthetic_bundle, delta, expected):
    py_path, manifest = synthetic_bundle
    data = json.loads(py_path.read_text())
    data['predicted_time_s'] += delta
    write(py_path, data)
    assert compare_results(py_path, manifest)['comparison_status'] == expected


@pytest.mark.parametrize('field,value', [
    ('input_sha256', '4' * 64), ('task_id', 'different_task'),
    ('initial_state', {'frame': 'other'}), ('parameters', {'test_duration_s': 0.8}),
    ('timing_boundary', 'other boundary'),
])
def test_rejects_noncomparable_inputs_and_configurations(synthetic_bundle, field, value):
    py_path, manifest = synthetic_bundle
    data = json.loads(py_path.read_text())
    data[field] = value
    write(py_path, data)
    with pytest.raises(EvidenceError, match=field):
        compare_results(py_path, manifest)


def test_rejects_wrong_upstream_commit(synthetic_bundle):
    py_path, manifest = synthetic_bundle
    data = json.loads(manifest.read_text())
    data['upstream']['commit'] = '0' * 40
    write(manifest, data)
    with pytest.raises(EvidenceError, match='commit'):
        compare_results(py_path, manifest)


def test_rejects_tampered_raw_output(synthetic_bundle):
    py_path, manifest = synthetic_bundle
    (manifest.parent / 'raw_trace.json').write_text('tampered')
    with pytest.raises(EvidenceError, match='hash mismatch'):
        compare_results(py_path, manifest)


@pytest.mark.parametrize('role', ['raw_trace', 'runtime_identity', 'original_input',
                                  'generated_steps', 'normalized_result'])
def test_rejects_missing_evidence_file(synthetic_bundle, role):
    py_path, manifest = synthetic_bundle
    (manifest.parent / (role + '.json')).unlink()
    with pytest.raises(EvidenceError, match=role):
        compare_results(py_path, manifest)


def test_rejects_path_traversal(synthetic_bundle):
    py_path, manifest = synthetic_bundle
    data = json.loads(manifest.read_text())
    data['files']['raw_trace']['path'] = '../python.json'
    write(manifest, data)
    with pytest.raises(EvidenceError, match='inside evidence directory'):
        compare_results(py_path, manifest)


def test_rejects_symlink_escape(synthetic_bundle):
    py_path, manifest = synthetic_bundle
    trace = manifest.parent / 'raw_trace.json'
    trace.unlink()
    trace.symlink_to(py_path)
    with pytest.raises(EvidenceError, match='escapes evidence directory'):
        compare_results(py_path, manifest)


@pytest.mark.parametrize('time', [-0.1, True, float('nan'), float('inf')])
def test_rejects_invalid_times(synthetic_bundle, time):
    py_path, manifest = synthetic_bundle
    data = json.loads(py_path.read_text())
    data['events'][0]['end_s'] = time
    write(py_path, data)
    with pytest.raises(EvidenceError):
        compare_results(py_path, manifest)


def test_rejects_missing_event_field(synthetic_bundle):
    py_path, manifest = synthetic_bundle
    data = json.loads(py_path.read_text())
    del data['events'][0]['resource']
    write(py_path, data)
    with pytest.raises(EvidenceError, match='resource'):
        compare_results(py_path, manifest)


def test_rejects_normalized_steps_disagreeing_with_captured_steps(synthetic_bundle):
    py_path, manifest = synthetic_bundle
    write(manifest.parent / 'generated_steps.json', [])
    seal(manifest.parent, 'generated_steps')
    with pytest.raises(EvidenceError, match='generated_steps'):
        compare_results(py_path, manifest)


def test_additional_step_detail_is_compared_not_silently_ignored(synthetic_bundle):
    py_path, manifest = synthetic_bundle
    data = json.loads(py_path.read_text())
    data['steps'][0]['key'] = 'A'
    write(py_path, data)
    report = compare_results(py_path, manifest)
    assert any(d['field'] == 'steps[0].key' for d in report['differences'])


def test_rejects_overflow_json_number_even_inside_parameters(synthetic_bundle):
    py_path, manifest = synthetic_bundle
    py_path.write_text(py_path.read_text().replace('0.5', '1e999', 1))
    with pytest.raises(EvidenceError, match='overflows'):
        compare_results(py_path, manifest)


def test_rejects_duplicate_json_fields(synthetic_bundle):
    py_path, manifest = synthetic_bundle
    py_path.write_text(py_path.read_text().replace('{', '{"task_id": "duplicate",', 1))
    with pytest.raises(EvidenceError, match='duplicate JSON key'):
        compare_results(py_path, manifest)


def test_python_regression_cannot_be_mislabeled_as_original_run(synthetic_bundle):
    py_path, manifest = synthetic_bundle
    metadata = json.loads(manifest.read_text())
    metadata['evidence_kind'] = 'original_run'
    write(manifest, metadata)
    with pytest.raises(EvidenceError, match='original_run requires cogtool_actr'):
        compare_results(py_path, manifest)
