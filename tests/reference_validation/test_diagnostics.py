"""Bounded synthetic diagnostics, kept separate from the original regression run.

Evidence type: synthetic_unit_test. These cases are neither upstream outputs nor
human observations. Some assertions intentionally remain failing when the public
API violates its documented validation/serialization contract; no xfail masks it.
Run this file separately and preserve its own exit code and output.
"""
from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from cogtool_py.engine import predict
from cogtool_py.generator import generate
from cogtool_py.io import load_project, save_project
from cogtool_py.models import DemonstrationStep, ModelError, ParameterSet, Project


EVIDENCE_TYPE = "synthetic_unit_test"
pytestmark = pytest.mark.independent


@pytest.fixture(autouse=True)
def evidence_type(record_property):
    record_property("evidence_type", EVIDENCE_TYPE)


def payload(steps=None, *, focus=None, hand="mouse"):
    widgets = [
        {"id": "button", "name": "run", "label": "运行", "kind": "button",
         "x": 10, "y": 10, "width": 20, "height": 20},
        {"id": "field", "name": "field", "label": "输入", "kind": "textbox",
         "x": 60, "y": 10, "width": 20, "height": 20},
    ]
    return {
        "schema_version": 1, "id": "synthetic-diagnostic", "name": "Synthetic diagnostic",
        "engine": "klm_baseline",
        "parameters": {name: {"value": value, "unit": "s", "source": EVIDENCE_TYPE}
                       for name, value in {"click_s": .2, "key_s": .2, "homing_s": .4}.items()},
        "design": {"id": "d", "name": "D", "coordinate_unit": "px",
                   "frames": [{"id": "f", "name": "F", "widgets": widgets}], "transitions": []},
        "tasks": [{"id": "t", "name": "T", "demonstration": {
            "initial": {"frame": "f", "mouse": [0, 0], "mouse_hand": "right",
                        "hand": hand, "focus": focus},
            "steps": steps if steps is not None else [{"op": "click", "target": "button"}],
        }}],
    }


def project(steps=None, **kwargs):
    return Project.from_dict(payload(steps, **kwargs))


def with_steps(model, *steps):
    task = model.tasks[0]
    return replace(model, tasks=(replace(task, demonstration=replace(task.demonstration, steps=steps)),))


def save_observation(name, data):
    directory = os.environ.get("COGTOOL_DIAGNOSTICS_DIR")
    if directory:
        target = Path(directory) / "observations" / (name + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"evidence_type": EVIDENCE_TYPE, **data},
                                     ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def result_without_runtime(model):
    result = dict(predict(model).to_dict())
    result.pop("program_runtime_s")
    return result


def test_point_then_click_has_one_point_component():
    result = predict(project([{"op": "point", "target": "button"},
                              {"op": "click", "target": "button"}])).data
    assert [e["op"] for e in result["events"]] == ["point", "think", "click"]
    assert sum(e["duration_s"] for e in result["events"] if e["op"] == "point") == pytest.approx(.15)


def test_mouse_keyboard_mouse_cycle_has_exactly_two_homings():
    result = predict(project([{"op": "click", "target": "field"},
                              {"op": "keys", "keys": ["h", "i"]},
                              {"op": "click", "target": "button"}])).data
    homes = [s for s in result["steps"] if s["op"] == "home"]
    assert [s["device"] for s in homes] == ["keyboard", "mouse"]
    assert sum(e["duration_s"] for e in result["events"] if e["op"] == "home") == pytest.approx(.8)
    assert result["final_state"]["hand"] == "mouse"


def test_continuous_keys_are_physical_strokes_without_extra_mental():
    result = predict(project([{"op": "keys", "keys": ["h", "i"]},
                              {"op": "keys", "keys": ["h"]}], focus="field")).data
    assert [e["op"] for e in result["events"]] == ["home", "key", "key", "key"]
    assert result["predicted_time_s"] == pytest.approx(1.0)


def test_json_shortcut_token_is_rejected():
    with pytest.raises(ModelError, match="CTRL\\+C"):
        project([{"op": "keys", "keys": ["CTRL+C"]}], focus="field")


def test_explicit_think_does_not_gain_an_automatic_think():
    result = predict(project([{"op": "think", "duration_s": .3},
                              {"op": "click", "target": "button"}])).data
    assert [e["op"] for e in result["events"]] == ["think", "point", "click"]
    assert result["predicted_time_s"] == pytest.approx(.65)


def test_explicit_look_at_preserves_baseline_no_extra_mental_contract():
    result = predict(project([{"op": "look_at", "target": "button", "duration_s": .3},
                              {"op": "click", "target": "button"}])).data
    assert [e["op"] for e in result["events"]] == ["look_at", "point", "click"]
    assert any("EMMA" in text for text in result["warnings"])


def test_expanded_script_json_is_rejected_as_demonstration():
    raw = payload()
    raw["tasks"][0]["demonstration"]["steps"] = predict(Project.from_dict(raw)).data["steps"]
    with pytest.raises(ModelError, match="unsupported field"):
        Project.from_dict(raw)


def test_expanded_script_objects_are_rejected_with_model_error():
    model = project()
    expanded = generate(model, model.tasks[0])
    invalid = with_steps(model, *expanded.steps)
    with pytest.raises(ModelError):
        predict(invalid)


def test_wait_boundaries_and_valid_model_roundtrip(tmp_path):
    raw = payload([{"op": "click", "target": "button", "transition": "go"},
                   {"op": "wait", "duration_s": .3}])
    raw["design"]["frames"].append({"id": "next", "name": "Next", "widgets": []})
    raw["design"]["transitions"] = [{"id": "go", "from_frame": "f", "target": "button",
                                      "to_frame": "next", "delay_s": .5}]
    model = Project.from_dict(raw)
    before = result_without_runtime(model)
    assert [e["op"] for e in before["events"]] == ["think", "point", "click", "wait", "transition", "wait"]
    assert [e["start_s"] for e in before["events"]] == pytest.approx([0, 1.2, 1.35, 1.55, 2.05, 2.05])
    assert before["predicted_time_s"] == pytest.approx(2.35)
    path = tmp_path / "roundtrip.json"
    save_project(model, path)
    assert result_without_runtime(load_project(path)) == before


def test_direct_unknown_operation_cannot_silently_produce_zero_prediction():
    invalid = with_steps(project(), DemonstrationStep(op="drag_not_implemented"))
    try:
        result = predict(invalid).data
    except ModelError:
        return
    save_observation("unknown_operation", {"direct_operation": "drag_not_implemented", "actual_result": result})
    pytest.fail("predict accepted unsupported direct operation; returned "
                f"{result['predicted_time_s']} s with {len(result['events'])} events")


def test_direct_unsupported_shortcut_cannot_be_counted_as_one_key():
    invalid = with_steps(project(focus="field"), DemonstrationStep(op="keys", keys=("CTRL+C",)))
    try:
        result = predict(invalid).data
    except ModelError:
        return
    save_observation("direct_shortcut", {"direct_keys": ["CTRL+C"], "actual_result": result})
    pytest.fail("predict accepted CTRL+C as one ordinary physical key through direct API")


def test_direct_empty_keys_fail_with_structured_model_error():
    invalid = with_steps(project(focus="field"), DemonstrationStep(op="keys", keys=()))
    with pytest.raises(ModelError):
        predict(invalid)


def test_direct_negative_think_is_rejected_by_engine_guard():
    invalid = with_steps(project(), DemonstrationStep(op="think", duration_s=-.1))
    # The same invalid duration now fails at the API boundary, before timing.
    with pytest.raises(ModelError, match=r"task\[t\].steps\[0\].duration_s"):
        predict(invalid)


def test_zero_distance_cannot_hide_zero_width_direct_widget():
    model = project([{"op": "point", "target": "button"}])
    frame = model.design.frames[0]
    invalid_widget = replace(frame.widgets[0], width=0)
    invalid = replace(model, design=replace(model.design, frames=(replace(frame, widgets=(invalid_widget,)),)))
    task = invalid.tasks[0]
    initial = replace(task.demonstration.initial, mouse=(10, 20))
    invalid = replace(invalid, tasks=(replace(task, demonstration=replace(task.demonstration, initial=initial)),))
    try:
        result = predict(invalid).data
    except ModelError:
        return
    save_observation("zero_width_at_target", {"invalid_width": 0, "mouse": [10, 20], "actual_result": result})
    pytest.fail("zero-width direct widget was accepted as zero-distance point")


def test_mutable_effective_default_parameter_changes_input_identity():
    model = project()
    before = predict(model).data
    # Contract migration: the old illegal mutation is now explicitly rejected;
    # the equivalent legal override must still change both time and identity.
    with pytest.raises(TypeError):
        model.parameters.entries["think_s"] = replace(model.parameters.entries["think_s"], value=2.4)
    updated = replace(model, parameters=model.parameters.override("think_s", 2.4, source=EVIDENCE_TYPE))
    after = predict(updated).data
    save_observation("default_parameter_identity", {"before": before, "after": after,
                     "mutation_rejected": True, "legal_override": "ParameterSet.override(think_s, 2.4)"})
    assert after["predicted_time_s"] - before["predicted_time_s"] == pytest.approx(1.2)
    assert after["input_sha256"] != before["input_sha256"], "effective parameter changed but reported model hash stayed equal"


def test_mutable_effective_default_survives_semantic_roundtrip(tmp_path):
    model = project()
    with pytest.raises(TypeError):
        model.parameters.entries["think_s"] = replace(model.parameters.entries["think_s"], value=2.4)
    model = replace(model, parameters=model.parameters.override("think_s", 2.4, source=EVIDENCE_TYPE))
    before = predict(model).data
    path = tmp_path / "mutated-default.json"
    save_project(model, path)
    after = predict(load_project(path)).data
    save_observation("default_parameter_roundtrip", {"before": before, "after": after,
                     "saved_project": json.loads(path.read_text(encoding="utf-8"))})
    assert after["predicted_time_s"] == before["predicted_time_s"], "save/load silently restored original default"
    assert after["input_sha256"] == before["input_sha256"]
    assert after["parameters"] == before["parameters"]


def test_direct_unknown_widget_kind_is_rejected():
    model = project()
    frame = model.design.frames[0]
    invalid_widget = replace(frame.widgets[0], kind="slider_not_supported")
    invalid = replace(model, design=replace(model.design, frames=(replace(frame, widgets=(invalid_widget,)),)))
    with pytest.raises(ModelError):
        predict(invalid)


def test_direct_parameter_unit_mismatch_is_rejected():
    model = project()
    with pytest.raises(TypeError):
        model.parameters.entries["click_s"] = replace(model.parameters.entries["click_s"], value=200, unit="ms")
    with pytest.raises(ModelError, match=r"parameters.click_s.unit"):
        model.parameters.override("click_s", 200, unit="ms", source=EVIDENCE_TYPE)
    # Reconstructing the whole parameter set is also a validated API boundary.
    invalid = dict(model.parameters.entries)
    invalid["click_s"] = replace(invalid["click_s"], value=200, unit="ms")
    with pytest.raises(ModelError, match=r"parameters.click_s.unit"):
        ParameterSet(invalid)
