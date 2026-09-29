"""Independent malformed-input cases, not observations of original CogTool.

Fixtures are authored here; expected errors follow the public input contract.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from cogtool_py.generator import validate
from cogtool_py.models import ModelError, Project


pytestmark = pytest.mark.independent


def valid_document() -> dict:
    """A standalone, intentionally small model, unrelated to other fixtures."""
    return {
        "schema_version": 1,
        "id": "validation-fixture",
        "name": "输入校验示例",
        "engine": "klm_baseline",
        "parameters": {
            name: {"value": value, "unit": "s", "source": "test assumption, not empirical or CogTool output"}
            for name, value in (("click_s", 0.2), ("key_s", 0.1), ("homing_s", 0.4))
        },
        "design": {
            "id": "design", "name": "测试界面", "coordinate_unit": "px",
            "frames": [{"id": "page", "name": "首页", "widgets": [
                {"id": "button", "name": "button", "label": "按钮", "kind": "button",
                 "x": 100, "y": 100, "width": 60, "height": 30},
                {"id": "field", "name": "field", "label": "输入框", "kind": "textbox",
                 "x": 200, "y": 100, "width": 120, "height": 30},
            ]}],
            "transitions": [],
        },
        "tasks": [{"id": "task", "name": "单击按钮", "demonstration": {
            "initial": {"frame": "page", "mouse": [0, 0], "mouse_hand": "right", "hand": "mouse", "focus": None},
            "steps": [{"op": "click", "target": "button"}],
        }}],
    }


def check(document: dict) -> Project:
    project = Project.from_dict(document)
    validate(project)
    return project


def set_value(document: dict, path: tuple, value: object) -> None:
    cursor = document
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value


def test_chinese_labels_are_valid_but_do_not_imply_ime_support():
    project = check(valid_document())
    assert project.name == "输入校验示例"
    assert project.design.frames[0].widgets[0].label == "按钮"


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), float("-inf"), True, "0.2", None])
@pytest.mark.parametrize("parameter", ["click_s", "key_s", "homing_s"])
def test_invalid_operation_parameters_are_rejected(parameter, value):
    document = valid_document()
    document["parameters"][parameter]["value"] = value
    with pytest.raises(ModelError, match=rf"parameters\.{parameter}\.value"):
        check(document)


@pytest.mark.parametrize("dimension", ["width", "height"])
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True])
def test_invalid_widget_dimensions_are_rejected(dimension, value):
    document = valid_document()
    document["design"]["frames"][0]["widgets"][0][dimension] = value
    with pytest.raises(ModelError, match=rf"design\.frames\[0\]\.widgets\[0\]\.{dimension}"):
        check(document)


@pytest.mark.parametrize("op", ["wait", "look_at", "think"])
@pytest.mark.parametrize("value", [-0.01, float("nan"), float("inf"), False])
def test_invalid_step_duration_has_task_step_and_field_context(op, value):
    document = valid_document()
    step = {"op": op, "duration_s": value}
    if op == "look_at":
        step["target"] = "button"
    document["tasks"][0]["demonstration"]["steps"] = [step]
    with pytest.raises(ModelError, match=r"task\[task\]\.steps\[0\]\.duration_s"):
        check(document)


@pytest.mark.parametrize("version", [True, False, "1", 1.0, 0, 3, None])
def test_only_supported_integer_schema_version_is_accepted(version):
    document = valid_document()
    document["schema_version"] = version
    with pytest.raises(ModelError, match="schema_version"):
        check(document)


@pytest.mark.parametrize("path", [
    (), ("design",), ("design", "frames", 0), ("design", "frames", 0, "widgets", 0),
    ("tasks", 0), ("tasks", 0, "demonstration"),
    ("tasks", 0, "demonstration", "initial"), ("tasks", 0, "demonstration", "steps", 0),
    ("parameters", "click_s"),
])
def test_unknown_fields_are_not_silently_ignored(path):
    document = valid_document()
    cursor = document
    for key in path:
        cursor = cursor[key]
    cursor["unsupported_field"] = "must not be ignored"
    with pytest.raises(ModelError, match="unsupported field"):
        check(document)


@pytest.mark.parametrize("op", ["double_click", "drag", "scroll", "type_text", "voice", "tap", "eval"])
def test_unsupported_operation_does_not_produce_a_partial_prediction(op):
    document = valid_document()
    document["tasks"][0]["demonstration"]["steps"].append({"op": op})
    with pytest.raises(ModelError, match=r"task\[task\]\.steps\[1\]\.op"):
        check(document)


@pytest.mark.parametrize("key", ["你", "拼音", "A", "SHIFT+a", "CTRL+C", "TAB", "F1", "ab", "", 1, None])
def test_ime_shift_chords_and_unimplemented_keys_are_rejected(key):
    document = valid_document()
    demo = document["tasks"][0]["demonstration"]
    demo["initial"]["focus"] = "field"
    demo["steps"] = [{"op": "keys", "keys": [key]}]
    with pytest.raises(ModelError, match=r"task\[task\]\.steps\[0\]\.keys\[0\]"):
        check(document)


@pytest.mark.parametrize("op", ["point", "click", "look_at"])
def test_missing_target_field_is_rejected(op):
    document = valid_document()
    step = {"op": op}
    if op == "look_at":
        step["duration_s"] = 0.2
    document["tasks"][0]["demonstration"]["steps"] = [step]
    with pytest.raises(ModelError, match=r"task\[task\]\.steps\[0\].*missing.*target"):
        check(document)


@pytest.mark.parametrize("op", ["point", "click", "look_at"])
def test_nonexistent_target_is_rejected_with_step_context(op):
    document = valid_document()
    step = {"op": op, "target": "absent"}
    if op == "look_at":
        step["duration_s"] = 0.2
    document["tasks"][0]["demonstration"]["steps"] = [step]
    with pytest.raises(ModelError, match=r"task\[task\]\.steps\[0\]\.target.*absent"):
        check(document)


@pytest.mark.parametrize("op", ["look_at", "wait"])
def test_visual_and_wait_durations_must_be_explicit(op):
    document = valid_document()
    step = {"op": op}
    if op == "look_at":
        step["target"] = "button"
    document["tasks"][0]["demonstration"]["steps"] = [step]
    with pytest.raises(ModelError, match="missing.*duration_s"):
        check(document)


def test_keys_without_focus_are_rejected():
    document = valid_document()
    document["tasks"][0]["demonstration"]["steps"] = [{"op": "keys", "keys": ["a"]}]
    with pytest.raises(ModelError, match=r"task\[task\]\.steps\[0\]\.keys.*focus"):
        check(document)


@pytest.mark.parametrize("focus", ["button", "absent"])
def test_initial_focus_must_reference_a_real_textbox(focus):
    document = valid_document()
    document["tasks"][0]["demonstration"]["initial"]["focus"] = focus
    with pytest.raises(ModelError, match=r"task\[task\]\.initial\.focus"):
        check(document)


@pytest.mark.parametrize("path,value,message", [
    (("engine",), "actr", "engine.*no automatic fallback"),
    (("design", "coordinate_unit"), "mm", "design.coordinate_unit"),
    (("parameters", "click_s", "unit"), "ms", "parameters.click_s.unit"),
    (("parameters", "click_s", "source"), "", "parameters.click_s.source"),
    (("tasks", 0, "demonstration", "initial", "frame"), "missing", "initial.frame"),
    (("tasks", 0, "demonstration", "initial", "mouse"), [0], "initial.mouse"),
    (("tasks", 0, "demonstration", "initial", "mouse"), [0, float("nan")], "initial.mouse"),
    (("tasks", 0, "demonstration", "initial", "hand"), "touchscreen", "initial.hand"),
    (("tasks", 0, "demonstration", "initial", "mouse_hand"), "both", "initial.mouse_hand"),
    (("design", "frames", 0, "widgets", 0, "kind"), "checkbox", "kind"),
])
def test_invalid_schema_values_have_field_context(path, value, message):
    document = valid_document()
    set_value(document, path, value)
    with pytest.raises(ModelError, match=message):
        check(document)


def transition_document() -> dict:
    document = valid_document()
    document["design"]["frames"].append({"id": "second", "name": "第二页", "widgets": []})
    document["design"]["transitions"] = [{"id": "next", "from_frame": "page", "target": "button", "to_frame": "second", "delay_s": 0.5}]
    document["tasks"][0]["demonstration"]["steps"][0]["transition"] = "next"
    return document


@pytest.mark.parametrize("field,value", [
    ("to_frame", "absent"), ("from_frame", "absent"), ("target", "absent"),
    ("delay_s", -1), ("delay_s", float("nan")), ("delay_s", True),
])
def test_invalid_transition_definitions_are_rejected(field, value):
    document = transition_document()
    document["design"]["transitions"][0][field] = value
    with pytest.raises(ModelError, match=rf"design.transitions.*{field}"):
        check(document)


def test_transition_must_be_explicit_and_match_clicked_widget():
    for selected in (None, "wrong"):
        document = transition_document()
        click = document["tasks"][0]["demonstration"]["steps"][0]
        if selected is None:
            click.pop("transition")
        else:
            click["transition"] = selected
        with pytest.raises(ModelError, match=r"task\[task\]\.steps\[0\]\.transition"):
            check(document)


def test_transition_for_a_different_widget_cannot_be_selected():
    document = transition_document()
    document["tasks"][0]["demonstration"]["steps"][0]["target"] = "field"
    with pytest.raises(ModelError, match=r"task\[task\]\.steps\[0\]\.transition"):
        check(document)


def test_ambiguous_transition_triggers_are_rejected():
    document = transition_document()
    duplicate = deepcopy(document["design"]["transitions"][0])
    duplicate["id"] = "another-next"
    document["design"]["transitions"].append(duplicate)
    with pytest.raises(ModelError, match="ambiguous click transition"):
        check(document)


def test_cross_page_input_cannot_reuse_previous_page_focus():
    document = transition_document()
    document["tasks"][0]["demonstration"]["initial"]["focus"] = "field"
    document["tasks"][0]["demonstration"]["steps"].append({"op": "keys", "keys": ["a"]})
    with pytest.raises(ModelError, match=r"task\[task\]\.steps\[1\]\.keys.*focus"):
        check(document)


@pytest.mark.parametrize("collection", ["frames", "widgets", "tasks", "transitions"])
def test_duplicate_identifiers_are_rejected(collection):
    document = transition_document()
    if collection == "tasks":
        items = document["tasks"]
    elif collection == "widgets":
        items = document["design"]["frames"][0]["widgets"]
    else:
        items = document["design"][collection]
    items.append(deepcopy(items[0]))
    with pytest.raises(ModelError, match="duplicate id"):
        check(document)


def test_all_tasks_are_checked_before_accepting_project():
    document = valid_document()
    later = deepcopy(document["tasks"][0])
    later["id"] = "later-invalid-task"
    later["demonstration"]["steps"] = [{"op": "click", "target": "absent"}]
    document["tasks"].append(later)
    with pytest.raises(ModelError, match=r"task\[later-invalid-task\]\.steps\[0\]\.target"):
        check(document)


def test_structural_roundtrip_preserves_semantics_without_mutating_input():
    document = transition_document()
    before = deepcopy(document)
    first = check(document)
    second = check(first.to_dict())
    assert second == first
    assert document == before
