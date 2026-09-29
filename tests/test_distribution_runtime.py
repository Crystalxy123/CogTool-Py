"""Installation/entrypoint contracts; no research tree or external backend needed."""
from dataclasses import replace
from importlib.resources import files
import csv
import json

import pytest

from cogtool_py.cli import main
from cogtool_py.control_models import ControlConfig
from cogtool_py.engine import predict
from cogtool_py.io import export_result, input_hash, load_project, save_project
from cogtool_py.models import CONTROL_ENGINE, DemonstrationStep, ModelError, Project
from cogtool_py.runtime import require_configuration, run_example, run_project, software_info


def baseline():
    return Project.from_dict(json.loads(files('cogtool_py').joinpath('resources', 'single_click.json').read_text()))


def integrated(scope='integrated_task'):
    p = baseline()
    return replace(p, engine=CONTROL_ENGINE,
                   parameters=p.parameters.with_vision_defaults() if scope == 'integrated_task' else p.parameters.with_control_defaults(),
                   control=replace(ControlConfig.source_2014(provenance='synthetic installation test'), execution_scope=scope))


def test_resource_and_public_api_work_outside_source_with_unicode_space(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / '中文 与 spaces'
    example = run_example(output)
    project = load_project(output / 'single_click.json')
    assert project.engine == 'klm_baseline'
    assert example['predicted_time_s'] == predict(project).data['predicted_time_s']
    result = run_project(output / 'single_click.json', engine='klm_baseline')
    assert result.data['distribution_identity']['execution_status'] == 'complete'
    assert result.data['distribution_identity']['scope'] == 'serial_baseline'
    with pytest.raises(ModelError, match='new directory'):
        run_example(output)


def test_strict_selection_cannot_change_saved_engine_scope_or_policy():
    p = integrated()
    before = input_hash(p)
    assert require_configuration(p, engine=CONTROL_ENGINE, scope='integrated_task', run_policy='legacy_bounded') is p
    for requested in [{'engine':'klm_baseline'}, {'scope':'prefix_only'}, {'run_policy':'reference_2014'}]:
        with pytest.raises(ModelError, match='no automatic conversion'):
            require_configuration(p, **requested)
    assert input_hash(p) == before


def test_version_domains_are_separate_and_match_real_calculation():
    info = software_info()
    assert info['package_version'] != info['engines']['klm_baseline']['version']
    actual = predict(integrated()).data
    assert actual['engine']['version'] == info['engines'][CONTROL_ENGINE]['integrated_task_version'] == '0.6.0'
    assert actual['distribution_identity']['scope'] == 'integrated_task'
    assert actual['distribution_identity']['run_policy'] == 'legacy_bounded'
    assert actual['distribution_identity']['default_parameter_versions']
    assert info['input_schema'] == {'read':[1,2], 'write':2}


def test_actual_control_motor_and_visual_records_survive_csv_export(tmp_path):
    data = predict(integrated())
    export_result(data, tmp_path)
    for name in ('events', 'motor_events', 'vision_events'):
        with (tmp_path / (name+'.csv')).open(encoding='utf-8', newline='') as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(data.data[name])
        for actual, original in zip(rows, data.data[name]):
            for key, value in original.items():
                if isinstance(value, (dict, list, tuple)):
                    assert json.loads(actual[key]) == json.loads(json.dumps(value))
                elif value is not None:
                    assert actual[key] == str(value)


def test_partial_cli_is_nonzero_and_keeps_no_task_total(tmp_path, capsys):
    p = integrated('prefix_only')
    task = p.tasks[0]
    p = replace(p, tasks=(replace(task, demonstration=replace(task.demonstration,
        steps=(DemonstrationStep('point', target=p.design.frames[0].widgets[0].id),))),))
    source = tmp_path / 'prefix.json'
    save_project(p, source)
    assert main(['predict', str(source), '--out', str(tmp_path/'partial')]) == 3
    data = json.loads((tmp_path/'partial/result.json').read_text())
    assert data['predicted_time_s'] is None
    assert data['distribution_identity']['execution_status'] == 'partial'
    assert 'no full task time' in capsys.readouterr().out


def test_invalid_input_and_configuration_do_not_leave_success_output(tmp_path, capsys):
    source = tmp_path / 'base.json'
    save_project(baseline(), source)
    assert main(['predict', str(source), '--engine', CONTROL_ENGINE, '--out', str(tmp_path/'wrong')]) == 2
    assert not (tmp_path/'wrong').exists()
    assert 'configuration.engine' in capsys.readouterr().err


def test_override_roundtrip_and_api_result_metadata_share_actual_parameters(tmp_path):
    original = baseline()
    modified = replace(original, parameters=original.parameters.override('think_s', 2.4, source='synthetic installation test'))
    saved = tmp_path/'override.json'
    save_project(modified, saved)
    a, b = predict(modified).data, run_project(saved, engine='klm_baseline').data
    assert input_hash(original) != input_hash(modified)
    assert a['distribution_identity'] == b['distribution_identity']
    assert a['parameters'] == b['parameters']
    assert a['events'] == b['events']
