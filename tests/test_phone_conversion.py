"""Pinned official-input conversion checks; archived predictions are not golden tests."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from cogtool_py.io import load_project
from cogtool_py.models import ModelError
from scripts.convert_phone_case import (
    CODE_COMMIT, DOC_COMMIT, ROOT, SOURCE_RULES, ConversionError, MODEL_PATH, MODEL_REL, MODEL_SHA256, baseline_parameters, construct_candidate,
    convert, extract_case, parent_chain, parse_persist, read_phone,
)

pytestmark = pytest.mark.integration


def require_external_git_objects(repository: Path, objects: list[str]) -> None:
    """Skip absent reference objects, but expose corrupt repositories/tool failures."""
    if not (repository / '.git').exists():
        pytest.skip(f'External reference Git repository unavailable: {repository.name}')
    git = shutil.which('git')
    if git is None:
        pytest.skip('Git is unavailable for external reference identity checks')
    result = subprocess.run([git, '-C', str(repository), 'cat-file', '--batch-check'],
                            input='\n'.join(objects) + '\n', capture_output=True, text=True, check=True)
    lines = result.stdout.splitlines()
    assert len(lines) == len(objects), 'Unexpected reference Git object-check response'
    missing = [obj for obj, line in zip(objects, lines) if line == f'{obj} missing']
    if missing:
        pytest.skip(f'Pinned external reference Git objects unavailable: {", ".join(missing)}')


@pytest.fixture(scope='module')
def official_archive():
    if not MODEL_PATH.is_file():
        pytest.skip('External official phone archive is not distributed with the core source')
    return MODEL_PATH


@pytest.fixture(scope='module')
def official_model(official_archive):
    require_external_git_objects(ROOT / 'documentation', [f'{DOC_COMMIT}:{MODEL_REL}'])


@pytest.fixture(scope='module')
def official_artifacts(tmp_path_factory, official_model):
    required = [ROOT / 'reference/upstream-cogtool' / rule[0] for rule in SOURCE_RULES]
    required.append(ROOT / '实验数据/CogTool_reference_catalog.json')
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        pytest.skip(f'External reference files unavailable: {", ".join(missing)}')
    require_external_git_objects(ROOT / 'cogtool', [f'{CODE_COMMIT}:{rule[0]}' for rule in SOURCE_RULES])
    out = tmp_path_factory.mktemp('official-phone-conversion')
    summary = convert(out, run=True)
    return out, summary


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def test_source_verified_and_complete_binding_is_np_b1(official_artifacts):
    out, summary = official_artifacts
    assert summary['source']['source_sha256'] == MODEL_SHA256
    assert summary['selection']['priority_examined'] == 'NP-A1'
    assert summary['selection']['selected_for_complete_baseline'] == 'NP-B1'
    extraction = read(out / 'NP-B1/extraction.json')
    assert (extraction['source_design'], extraction['source_task']) == ('Pop-Up', 'Look up one number')
    assert extraction['task_application_object_id'] == '283'
    assert extraction['initial_state_object_id'] == '285'


def test_np_b1_preserves_one_demonstration_and_full_original_start_frame(official_artifacts):
    out, _ = official_artifacts
    candidate = read(out / 'NP-B1/candidate_input.json')
    assert candidate['tasks'][0]['demonstration']['steps'] == [
        {'op': 'menu_select', 'target': 'w22', 'transition': 't25'}]
    widgets = {w['id']: w for w in candidate['design']['frames'][0]['widgets']}
    assert len(widgets) == 10
    assert widgets['w22']['parent'] == 'w8'
    assert widgets['w8']['parent'] is None
    assert widgets['w22']['kind'] == 'menu_item'
    assert widgets['w8']['kind'] == 'context_menu'
    assert [widgets['w22'][k] for k in ['x', 'y', 'width', 'height']] == [64.0, 345.5, 119.0, 15.75]
    assert candidate['design']['transitions'] == [
        {'id': 't25', 'from_frame': 'f6', 'target': 'w22', 'to_frame': 'f6', 'delay_s': 0.0}]
    mapped = read(out / 'NP-B1/field_mapping.json')['fields']
    assert len([m for m in mapped if '.widgets[' in m['python_field']]) == 10


def test_initial_mouse_comes_from_source_rule_and_hand_from_saved_object(official_artifacts):
    out, _ = official_artifacts
    extraction = read(out / 'NP-B1/extraction.json')
    initial = read(out / 'NP-B1/candidate_input.json')['tasks'][0]['demonstration']['initial']
    assert initial == {'frame': 'f6', 'mouse': [0, 0], 'mouse_hand': 'right', 'hand': 'mouse', 'focus': None}
    assert extraction['initial_derived']['source'].endswith('cogtool-run-model:1150-1151')
    assert extraction['initial_derived']['source_version'] == '1.3-2014-02-10'
    assert extraction['initial_derived']['archived_2009_mouse'] is None
    assert extraction['initial_derived']['status'] == 'conditional_2014_default_not_verified_for_2009_r3035'
    assert extraction['initial_saved']['rightHandLoc'] == 'M'
    assert extraction['initial_widget_references']['lastClickedWidget'] is None


def test_np_a1_keeps_exact_menu_and_visual_blockers_without_inventing_duration(official_artifacts):
    out, _ = official_artifacts
    blockers = read(out / 'NP-A1/blockers.json')
    assert blockers['complete_baseline_input'] is False
    assert blockers['first_blocker']['demonstration_index'] == 0
    assert blockers['first_blocker']['object_id'] == '530'
    assert blockers['first_blocker']['parent_chain_object_ids'] == ['212', '248', '233']
    assert any(b['object_id'] == '532' and b['field'] == 'duration_s' for b in blockers['blockers'])
    candidate = read(out / 'NP-A1/candidate_input.json')
    assert candidate['tasks'][0]['demonstration']['steps'][2]['duration_s'] is None
    assert len(candidate['tasks'][0]['demonstration']['steps']) == 6
    with pytest.raises(ModelError):
        load_project(out / 'NP-A1/candidate_input.json')
    assert not (out / 'NP-A1/python_prediction/result.json').exists()


def test_real_cli_runs_baseline_and_four_numeric_sources_stay_separate(official_artifacts):
    out, _ = official_artifacts
    summary = read(out / 'summary.json')
    assert summary['status'] == 'DIAGNOSTIC_ONLY'
    assert summary['original_rerun_s'] is None
    assert summary['published_prediction_s'] == 3.5
    assert summary['archived_prediction_s'] == 2.6450002
    result = read(out / summary['result_path'])
    assert result['predicted_time_s'] == summary['diagnostic_python_prediction_s'] > 0
    assert result['validation']['original_comparison'] == 'unverified'
    assert summary['original_equivalence_claim'] is False
    assert [step['op'] for step in result['steps']] == ['point', 'right_click', 'think', 'point', 'click', 'transition']
    assert result['final_state']['mouse'] == [123.0, 352.5]
    assert read(out / 'NP-B1/validate.process.json')['returncode'] == 0
    assert read(out / 'NP-B1/predict.process.json')['returncode'] == 0


def test_motor_assumptions_copied_unchanged_not_fitted_to_legacy_times(official_artifacts):
    out, summary = official_artifacts
    parameters, profile = baseline_parameters()
    candidate = read(out / 'NP-B1/candidate_input.json')
    assert candidate['parameters'] == parameters
    assert profile['values'] == summary['baseline_parameter_profile']['values']
    assert 'not fitted' in profile['use']


def test_cached_times_and_generated_steps_cannot_drive_candidate_input(official_model):
    # Synthetic mutation of an in-memory graph, never an original-run reference.
    graph, _ = read_phone()
    parameters, _ = baseline_parameters()
    extraction = extract_case(graph, 'NP-B1')
    before = construct_candidate(graph, extraction, parameters)[0]
    for node in graph.root.iter('dbl'):
        if node.get('var') in {'taskTime', 'duration'}:
            node.set('val', '99999')
    for node in graph.root.iter('str'):
        if node.get('var') == 'label':
            node.text = 'SYNTHETIC MUTATION@'
    after = construct_candidate(graph, extract_case(graph, 'NP-B1'), parameters)[0]
    assert before == after


def test_tampered_official_archive_is_rejected(tmp_path, official_archive):
    bad = tmp_path / 'N&P93.cgt.zip'
    bad.write_bytes(MODEL_PATH.read_bytes() + b'changed')
    with pytest.raises(ConversionError, match='SHA-256'):
        read_phone(bad)


@pytest.mark.parametrize('payload', [
    b'<!DOCTYPE persist [<!ENTITY x "x">]><persist version="2"/>',
    b'<persist version="99"/>', b'<not-xml',
])
def test_rejects_unsafe_or_unexpected_persistence_xml(payload):
    with pytest.raises(ConversionError):
        parse_persist(payload)


def test_widget_parent_cycle_is_rejected(official_model):
    graph, _ = read_phone()
    parent = graph.index['22'].find("ref[@var='parent']")
    parent.set('idref', '22')
    with pytest.raises(ConversionError, match='Cyclic'):
        parent_chain(graph, graph.index['22'])


def test_unsupported_case_and_context_menu_override_fail_closed(official_model):
    graph, _ = read_phone()
    with pytest.raises(ConversionError, match='Only explicit'):
        extract_case(graph, 'NP-B2')
    target = graph.index['8']
    ET.SubElement(target, 'int', {'var': 'WidgetType.contextMenuAction', 'val': '1'})
    parameters, _ = baseline_parameters()
    with pytest.raises(ConversionError, match='Unsupported context-menu'):
        construct_candidate(graph, extract_case(graph, 'NP-B1'), parameters)


def test_output_cannot_target_source_directories():
    from scripts.convert_phone_case import ROOT
    with pytest.raises(ConversionError, match='source or user input'):
        convert(ROOT / 'reference')


def test_existing_output_is_rejected_without_changing_evidence(tmp_path):
    from scripts.convert_phone_case import sha
    existing = tmp_path / 'prior_evidence'
    existing.mkdir()
    old = existing / 'summary.json'
    old.write_text('{"historical":true}')
    before = sha(old.read_bytes())
    with pytest.raises(ConversionError, match='historical evidence'):
        convert(existing)
    assert sha(old.read_bytes()) == before
    assert list(existing.iterdir()) == [old]


def test_missing_object_reference_has_field_context():
    with pytest.raises(ConversionError, match="field 'parent'.*missing object '404'"):
        parse_persist(b'<persist version="2"><obj id="1"/><ref var="parent" idref="404"/></persist>')


def test_cli_timeout_preserves_output_and_reports_no_prediction(tmp_path, monkeypatch):
    from scripts import convert_phone_case as converter
    import subprocess
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 30, output=b'partial stdout', stderr=b'partial stderr')
    monkeypatch.setattr(converter.subprocess, 'run', timeout)
    result = converter.run_python(tmp_path / 'candidate.json', tmp_path)
    assert result['status'] == 'python_cli_timeout'
    assert result['diagnostic_python_prediction_s'] is None
    record = read(tmp_path / 'validate.process.json')
    assert record['returncode'] is None
    assert record['outcome'] == 'timeout'
    assert record['wall_clock_runtime_s'] >= 0
    assert (tmp_path / 'validate.stdout.txt').read_text() == 'partial stdout'
    assert (tmp_path / 'validate.stderr.txt').read_text() == 'partial stderr'
    assert not (tmp_path / 'predict.process.json').exists()
