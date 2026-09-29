"""Desktop boundary checks: keep model identity and incomplete-run semantics."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from desktop.bridge import inspect_project, run_prediction
from cogtool_py.engine import predict
from cogtool_py.control_models import ControlConfig
from cogtool_py.io import input_hash, load_project, read_json, save_project
from cogtool_py.models import CONTROL_ENGINE, DemonstrationStep, ModelError


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "single_click.json"


def test_inspection_exposes_saved_tasks_and_engine():
    data = inspect_project(EXAMPLE)
    assert data["engine"] == "klm_baseline"
    assert data["tasks"] == [{"id": "single_click", "name": "点击运行", "step_count": 1}]


def test_desktop_prediction_matches_public_engine_and_saves_input(tmp_path):
    original = load_project(EXAMPLE)
    expected = predict(original, "single_click").data
    output = tmp_path / "中文 空格结果"
    payload, status = run_prediction(EXAMPLE, "single_click", output)
    assert status == 0
    result = payload["result"]
    assert result["predicted_time_s"] == expected["predicted_time_s"]
    assert result["events"] == expected["events"]
    assert result["input_sha256"] == input_hash(original)
    assert input_hash(load_project(output / "input.json")) == input_hash(original)
    serialized_result = json.loads(json.dumps(result))
    assert read_json(output / "result.json") == serialized_result
    assert (output / "events.csv").is_file()
    assert (output / "steps.csv").is_file()
    with pytest.raises(ModelError, match="already exists"):
        run_prediction(EXAMPLE, "single_click", output)
    assert read_json(output / "result.json") == serialized_result


def test_unknown_task_does_not_create_output(tmp_path):
    output = tmp_path / "invalid"
    with pytest.raises(ModelError, match="Unknown task"):
        run_prediction(EXAMPLE, "missing", output)
    assert not output.exists()


def test_partial_prediction_preserves_null_time_and_trace(tmp_path):
    model = load_project(EXAMPLE)
    task = model.tasks[0]
    task = replace(task, demonstration=replace(task.demonstration,
        steps=(DemonstrationStep("point", target="button"),)))
    model = replace(model, engine=CONTROL_ENGINE,
        parameters=model.parameters.with_control_defaults(),
        control=ControlConfig.source_2014(provenance="desktop boundary test"),
        tasks=(task,))
    source = tmp_path / "partial.json"
    save_project(model, source)
    payload, status = run_prediction(source, task.id, tmp_path / "partial-output")
    assert status == 3
    assert payload["result"]["predicted_time_s"] is None
    assert payload["result"]["distribution_identity"]["execution_status"] == "partial"
    assert (tmp_path / "partial-output" / "result.json").exists()


def test_selected_task_is_used_in_multi_task_model(tmp_path):
    model = load_project(EXAMPLE)
    selected = replace(model.tasks[0], id="second-task", name="第二个任务")
    source = tmp_path / "multiple.json"
    save_project(replace(model, tasks=(*model.tasks, selected)), source)
    payload, status = run_prediction(source, selected.id, tmp_path / "selected-output")
    assert status == 0
    assert payload["result"]["task_id"] == selected.id
