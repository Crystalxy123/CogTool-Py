"""Independent source-profile checks; no archived timings define expectations."""
from dataclasses import replace
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from cogtool_py.control_models import AuxiliaryLocation, ControlConfig, SyntheticUpdate
from cogtool_py.engine import predict
from cogtool_py.io import input_hash, load_project, save_project
from cogtool_py.models import CONTROL_ENGINE, ModelError, Project
from scripts.convert_phone_case import DOC_COMMIT, MODEL_PATH, MODEL_REL, baseline_parameters, construct_candidate, extract_case, read_phone
from scripts.extract_control_scene import CODE_COMMIT, SOURCES, extract_scene

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.independent


@pytest.fixture(scope='module')
def source_scene():
    required = [MODEL_PATH, *(ROOT / 'reference/upstream-cogtool' / source[0] for source in SOURCES)]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        pytest.skip(f'External reference files unavailable: {", ".join(missing)}')
    git = shutil.which('git')
    if git is None:
        pytest.skip('Git is unavailable for external reference identity checks')
    for repository, objects in (
        (ROOT / 'documentation', [f'{DOC_COMMIT}:{MODEL_REL}']),
        (ROOT / 'cogtool', [f'{CODE_COMMIT}:{source[0]}' for source in SOURCES]),
    ):
        if not (repository / '.git').exists():
            pytest.skip(f'External reference Git repository unavailable: {repository.name}')
        # A missing object is a skip; malformed repositories, conversion errors,
        # source hash mismatches and calculation failures still fail the test.
        result = subprocess.run([git, '-C', str(repository), 'cat-file', '--batch-check'],
                                input='\n'.join(objects) + '\n', capture_output=True, text=True, check=True)
        lines = result.stdout.splitlines()
        assert len(lines) == len(objects), 'Unexpected reference Git object-check response'
        absent = [obj for obj, line in zip(objects, lines) if line == f'{obj} missing']
        if absent:
            pytest.skip(f'Pinned external reference Git objects unavailable: {", ".join(absent)}')
    return extract_scene()


@pytest.fixture(scope='module')
def source_project(source_scene):
    graph, _ = read_phone()
    candidate, _, blockers = construct_candidate(graph, extract_case(graph, 'NP-B1'), baseline_parameters()[0])
    assert blockers == []
    project = Project.from_dict(candidate)
    auxiliary = tuple(AuxiliaryLocation(a['id'], a['frame'], a['x'], a['y'],
                      f"fixed {CODE_COMMIT}; original SimpleWidgetGroup {a['source']['object_id']}; union original members")
                      for a in source_scene['auxiliary_locations'])
    return replace(project, schema_version=2, engine=CONTROL_ENGINE,
                   parameters=project.parameters.with_control_defaults(),
                   control=ControlConfig.source_2014(provenance='Source-defined 2014 normal initialization; not original runtime output',
                                                    auxiliary_locations=auxiliary))


def test_actual_scene_includes_ten_widgets_and_two_original_groups(source_scene):
    # Object 12: union four rectangles x64,y314,w119,h63. Object 36 is
    # translated (+1,+40). Fixed source floors each half-dimension.
    assert len(source_scene['widgets']) == 10
    assert [(a['id'], a['center'], a['source']['members']) for a in source_scene['auxiliary_locations']] == [
        ('g12', [123, 345], ['14', '18', '22', '28']),
        ('g36', [124, 385], ['32', '38', '46', '52']),
    ]
    points = {a['id']: a['center'] for a in source_scene['widgets'] + source_scene['auxiliary_locations']}
    assert points['w8'] == [64, 313]
    assert points['w42'] == [65, 353]
    assert points['w22'] == [123, 352.5]
    assert all(point[0] > 64 for name, point in points.items() if name != 'w8')
    assert source_scene['normal_stuffing']['leftmost_candidates'] == ['w8']
    assert source_scene['normal_stuffing']['requested'] is False
    assert source_scene['visibility_contract']['menu_items_in_initial_scene'] is True
    assert source_scene['visibility_contract']['ordinary_cogtool_emitVirtualFrames'] is False
    assert source_scene['unknowns']['source_2009_commit'] is None
    assert all(a['order'] is None for a in source_scene['auxiliary_locations'])


def test_source_profile_starts_without_scene_then_stuffs_unique_leftmost(source_project):
    result = predict(source_project).data
    initial = result['events'][0]['state_after']
    assert initial['current_frame'] is None
    assert initial['scene_locations'] == []
    assert initial['visual_location'] is None
    assert initial['visual_content'] is None
    assert all(initial[key] == 'free' for key in ('visual_preparation', 'visual_processor', 'visual_execution'))
    display = next(e for e in result['events'] if e['event_type'] == 'proc_display')
    assert set(display['state_after']['scene_locations']) == {'w8', 'w14', 'w18', 'w22', 'w28',
                                                             'w32', 'w38', 'w42', 'w46', 'w52', 'g12', 'g36'}
    stuffed = next(e for e in result['events'] if e['event_type'] == 'visual_location_stuffed')
    assert stuffed['start_s'] == 0
    assert stuffed['state_after']['visual_location']['target'] == 'w8'
    assert stuffed['state_after']['location_requested'] is False
    assert stuffed['state_after']['visual_content'] is None
    assert stuffed['details']['event_priority'] == 10
    assert result['first_target_rule'] == 'look-at'
    assert result['completion_status'] == 'partial'
    assert result['reported_task_time_s'] is None
    assert result['original_rerun_s'] is None


def test_source_config_save_reload_hash_covers_auxiliary_geometry_and_source(source_project, tmp_path):
    destination = tmp_path / 'source-profile.json'
    save_project(source_project, destination)
    restored = load_project(destination)
    assert restored == source_project
    assert input_hash(restored) == input_hash(source_project)
    assert restored.control.profile == 'source_2014_defaults'
    assert len(restored.control.auxiliary_locations) == 2
    first, second = restored.control.auxiliary_locations
    for altered in (replace(first, x=first.x + 1), replace(first, source=first.source + '; audit update')):
        changed = replace(restored, control=replace(restored.control, auxiliary_locations=(altered, second)))
        assert input_hash(changed) != input_hash(restored)


@pytest.mark.parametrize('changes', [
    {'visual_location': 'w8'}, {'location_requested': True}, {'visual_content': 'w8'},
    {'visual_preparation': 'busy'}, {'visual_processor': 'busy'}, {'visual_execution': 'busy'},
    {'frame_visible': False}, {'auto_stuffing': False}, {'visible_targets': ('w8',)},
    {'updates': (SyntheticUpdate(.01, 'location_set', 'w8'),)},
])
def test_source_profile_refuses_prescribed_or_synthetic_visual_state(source_project, changes):
    with pytest.raises(ModelError, match='source_2014_defaults cannot contain prescribed/synthetic state'):
        predict(replace(source_project, control=replace(source_project.control, **changes)))


def test_source_profile_refuses_prescribed_nonzero_cursor(source_project):
    task = source_project.tasks[0]
    altered = replace(task, demonstration=replace(task.demonstration,
                      initial=replace(task.demonstration.initial, mouse=(99, 99))))
    with pytest.raises(ModelError, match=r'source_2014_defaults resets cursor to \(0,0\)'):
        predict(replace(source_project, tasks=(altered,)))
    # The same prescribed coordinates remain representable as synthetic input.
    synthetic = replace(source_project, tasks=(altered,), control=replace(source_project.control,
                        profile='synthetic_controller_only', provenance='Synthetic cursor test',
                        visual_location='w8', auto_stuffing=False))
    assert predict(synthetic).data['initial_state']['mouse'] == (99, 99)


def test_synthetic_requested_origin_survives_serialization(source_project, tmp_path):
    source = replace(source_project, control=replace(source_project.control,
                    profile='synthetic_controller_only', provenance='Synthetic requested-flag persistence check',
                    visual_location='w8', location_requested=True, auto_stuffing=False))
    destination = tmp_path / 'synthetic.json'
    save_project(source, destination)
    restored = load_project(destination)
    assert restored.control.location_requested is True
    assert restored.control.visual_location == 'w8'
    assert input_hash(restored) == input_hash(source)
    assert input_hash(source) != input_hash(source_project)


@pytest.mark.parametrize('field,value', [('max_events', 0), ('max_events', True), ('max_events', 100001),
                                       ('max_time_s', 0), ('max_time_s', float('inf')),
                                       ('max_time_s', 1e308)])
def test_invalid_limits_fail_as_model_errors(source_project, field, value):
    with pytest.raises(ModelError):
        predict(replace(source_project, control=replace(source_project.control, **{field: value})))


@pytest.mark.parametrize('changes,status', [({'max_events': 1}, 'event_limit'),
                                          ({'max_time_s': .01}, 'time_limit')])
def test_source_profile_limit_reports_snapshot_without_claiming_completion(source_project, changes, status):
    result = predict(replace(source_project, control=replace(source_project.control, **changes))).data
    assert result['completion_status'] == status
    assert result['reported_task_time_s'] is None
    assert result['first_mouse_request_time_s'] is None
    assert result['final_state']['time_s'] <= .01
    assert result['events'][-1]['event_type'] == 'prefix_boundary'
    assert result['events'][-1]['details']['full_task_completed'] is False


def test_scene_extractor_refuses_existing_output_without_changing_bytes(tmp_path):
    output = tmp_path / 'existing-evidence'
    output.mkdir()
    original = output / 'scene.json'
    original.write_text('{"existing":true}\n')
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/extract_control_scene.py'),
                             '--out', str(output)], cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert 'refuse overwrite' in result.stderr
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before
    assert list(output.iterdir()) == [original]
