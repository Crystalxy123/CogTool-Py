"""Synthetic direct-API boundaries and independent menu sequence expectations.

These cases do not constitute original CogTool execution or timing evidence.
Fixtures intentionally use actual dataclasses, bypassing the JSON parser.
"""
from dataclasses import replace
import hashlib
import json

import pytest

import cogtool_py.engine as engine
import cogtool_py.generator as generator
from cogtool_py.io import input_hash
from cogtool_py.models import (
    Demonstration, DemonstrationStep, Design, Frame, InitialState, ModelError,
    ParameterSet, Project, Task, Transition, Widget,
)
from cogtool_py.validation import validate_project


pytestmark = pytest.mark.independent


def parameters():
    return ParameterSet.parse({name: {"value": value, "unit": "s",
                                     "source": "synthetic_unit_test assumption"}
                               for name, value in {"click_s": .2, "key_s": .1, "homing_s": .4}.items()})


def widget(ident="field", kind="textbox", x=10, y=10, parent=None):
    return Widget(ident, ident, ident, kind, x, y, 20, 20, parent)


def project(steps=None, *, widgets=None, initial=None, transitions=(), extra_frames=()):
    return Project(2, "synthetic-api", "Synthetic API", "klm_baseline", parameters(),
                   Design("d", "D", "px", (Frame("f", "F", widgets or (widget(),)), *extra_frames), transitions),
                   (Task("task", "T", Demonstration(
                       initial or InitialState("f", (0, 0), "right", "mouse", "field"),
                       steps if steps is not None else (DemonstrationStep("keys", keys=("a",)),))),))


def with_steps(p, steps):
    return replace(p, tasks=(replace(p.tasks[0], demonstration=replace(p.tasks[0].demonstration, steps=steps)),))


@pytest.mark.parametrize("bad", [None, {}, [], "project"])
def test_predict_rejects_non_project_object(bad):
    with pytest.raises(ModelError, match="project: expected Project"):
        engine.predict(bad)


@pytest.mark.parametrize("step,field", [
    (DemonstrationStep("unknown"), "op"),
    (DemonstrationStep("keys"), "keys"),
    (DemonstrationStep("keys", keys=("CTRL+C",)), "keys"),
    (DemonstrationStep("keys", keys=["a"]), "keys"),
    (DemonstrationStep("click", target="field", duration_s=.2), "duration_s"),
    (DemonstrationStep("keys", keys=("a",), target="field"), "target"),
    (DemonstrationStep("wait", duration_s=float("nan")), "duration_s"),
    (DemonstrationStep("think", duration_s=float("inf")), "duration_s"),
    (DemonstrationStep("look_at", target="field"), "duration_s"),
    (DemonstrationStep("home", device="touchscreen"), "device"),
])
def test_actual_step_fields_rejected_at_predict_and_generate(step, field):
    p = project((step,))
    for action in (lambda: engine.predict(p), lambda: generator.generate(p, p.tasks[0])):
        with pytest.raises(ModelError, match=rf"task\[task\]\.steps\[0\].*{field}"):
            action()


def test_expanded_script_is_not_reinterpreted_as_demonstration():
    p = project()
    expanded = generator.generate(p, p.tasks[0])
    invalid = with_steps(p, expanded.steps)
    with pytest.raises(ModelError, match=r"task\[task\]\.steps\[0\].*ScriptStep"):
        engine.predict(invalid)


@pytest.mark.parametrize("mouse", [(float("nan"), 0), (0, float("inf")), (True, 0), (0,), "00"])
def test_actual_initial_mouse_validation(mouse):
    p = project(initial=InitialState("f", mouse, "right", "mouse", "field"))
    with pytest.raises(ModelError, match=r"task\[task\]\.initial\.mouse"):
        engine.predict(p)


@pytest.mark.parametrize("field,value", [("width", 0), ("height", -1), ("x", float("nan")),
                                         ("y", float("inf")), ("kind", "slider")])
def test_point_api_validates_widget_even_at_zero_distance(field, value):
    invalid = replace(widget(), **{field: value})
    with pytest.raises(ModelError, match=rf"point\.widget\.{field}"):
        engine.point_time((20, 20), invalid, parameters())


def test_point_api_validates_mouse_and_parameters_before_zero_shortcut():
    with pytest.raises(ModelError, match=r"point\.mouse\[0\]"):
        engine.point_time((True, 20), widget(), parameters())
    with pytest.raises(ModelError, match="parameters: expected ParameterSet"):
        engine.point_time((20, 20), widget(), {})


def test_direct_point_rejects_derived_overflow():
    p = parameters().override("motor_initiation_s", 1e308, source="synthetic overflow")
    p = p.override("fitts_min_s", 1e308, source="synthetic overflow")
    with pytest.raises(ModelError, match="computed time is out of range"):
        engine.point_time((0, 0), widget(), p)


def test_direct_point_rejects_scale_underflow_with_structured_error():
    p = parameters().override("pixels_per_inch", 1e-300, source="synthetic underflow")
    p = p.override("viewing_distance_in", 1e-300, source="synthetic underflow")
    with pytest.raises(ModelError, match="point geometry/parameters: derived value"):
        engine.point_time((0, 0), widget(), p)


def test_negative_coordinates_are_valid_and_translation_preserves_time():
    negative = widget(x=-30, y=-30)
    duration, _ = engine.point_time((-40, -40), negative, parameters())
    assert duration == pytest.approx(.15, abs=1e-12)
    assert engine.point_time((-20, -20), negative, parameters())[0] == 0
    p = project((DemonstrationStep("point", target="field"),), widgets=(negative,),
                initial=InitialState("f", (-40, -40), "right", "mouse", None))
    assert engine.predict(p).data["predicted_time_s"] == pytest.approx(.15, abs=1e-12)


def test_validator_does_not_generate_or_serialize(monkeypatch):
    p = project()
    def forbidden(*args, **kwargs):
        raise AssertionError("validation must inspect actual objects only")
    monkeypatch.setattr(generator, "generate", forbidden)
    monkeypatch.setattr(generator, "_generate_validated", forbidden)
    monkeypatch.setattr(Project, "to_dict", forbidden)
    monkeypatch.setattr(Project, "from_dict", forbidden)
    validate_project(p)
    with pytest.raises(ModelError, match=r"steps\[0\]\.duration_s"):
        validate_project(with_steps(p, (DemonstrationStep("click", target="field", duration_s=.4),)))


def test_prediction_generates_exactly_once(monkeypatch):
    calls = []
    implementation = engine._generate_validated
    def counted(*args):
        calls.append(args)
        return implementation(*args)
    monkeypatch.setattr(engine, "_generate_validated", counted)
    assert engine.predict(project()).data["predicted_time_s"] == pytest.approx(.1, abs=1e-12)
    assert len(calls) == 1


def test_generate_rejects_foreign_task_object():
    p = project()
    with pytest.raises(ModelError, match="selected Task"):
        generator.generate(p, replace(p.tasks[0]))


def test_missing_actual_dataclass_field_is_structured_error():
    empty = object.__new__(Project)
    with pytest.raises(ModelError, match="project.schema_version: required field"):
        engine.predict(empty)


def test_dynamic_frame_path_checks_target_and_clears_focus():
    next_frame = Frame("next", "Next", (widget("other"),))
    go = Transition("go", "f", "field", "next", .3)
    first = DemonstrationStep("click", target="field", transition="go")
    for final_step, field in [(DemonstrationStep("keys", keys=("a",)), "keys"),
                              (DemonstrationStep("point", target="field"), "target")]:
        p = project((first, final_step), transitions=(go,), extra_frames=(next_frame,))
        with pytest.raises(ModelError, match=rf"task\[task\]\.steps\[1\]\.{field}"):
            validate_project(p)


def test_self_transition_retains_textbox_focus_and_wait_is_serial():
    p = project((DemonstrationStep("click", target="field", transition="stay"),
                 DemonstrationStep("keys", keys=("a",))),
                transitions=(Transition("stay", "f", "field", "f", .3),))
    result = engine.predict(p).data
    assert [event["op"] for event in result["events"]] == ["think", "point", "click", "wait", "transition", "key"]
    assert result["events"][3]["start_s"] == pytest.approx(1.55, abs=1e-12)
    assert result["events"][4]["end_s"] == pytest.approx(1.85, abs=1e-12)
    assert result["predicted_time_s"] == pytest.approx(1.95, abs=1e-12)
    assert result["final_state"]["focus"] == "field"


def menu_project(steps=None, **kwargs):
    return project(steps or (DemonstrationStep("menu_select", target="item"),),
                   widgets=(widget("menu", "context_menu"), widget("item", "menu_item", x=20, parent="menu")),
                   initial=InitialState("f", (0, 0), "right", "keyboard", None), **kwargs)


def test_single_closed_context_menu_has_right_click_then_think_and_item_click():
    # Both points have angle D/W <= 1, so each is .05 initiation + .1 floor.
    # .4 home + .15 point + .2 right click + 1.2 Think + .15 point + .2 click = 2.3 s.
    result = engine.predict(menu_project()).data
    assert [step["op"] for step in result["steps"]] == ["home", "point", "right_click", "think", "point", "click"]
    assert [step["target"] for step in result["steps"]] == [None, "menu", "menu", None, "item", "item"]
    assert [step["origin"] for step in result["steps"]] == ["automatic"] * 5 + ["demonstrated"]
    assert [step["demo_index"] for step in result["steps"]] == [0] * 6
    assert result["events"][2]["resource"] == "motor"
    assert result["events"][2]["details"]["parameter"] == "click_s"
    assert result["events"][2]["duration_s"] == .2
    assert result["predicted_time_s"] == pytest.approx(2.3, abs=1e-12)
    assert result["demonstration"] == [{"op": "menu_select", "target": "item"}]
    assert any("single initially closed context menu" in warning for warning in result["warnings"])


def test_menu_response_wait_occurs_only_after_item_click():
    p = menu_project((DemonstrationStep("menu_select", target="item", transition="stay"),),
                     transitions=(Transition("stay", "f", "item", "f", .7),))
    result = engine.predict(p).data
    assert [event["op"] for event in result["events"]][-3:] == ["click", "wait", "transition"]
    assert result["events"][-2]["start_s"] == pytest.approx(2.3, abs=1e-12)
    assert result["events"][-2]["end_s"] == pytest.approx(3.0, abs=1e-12)
    assert result["events"][-1]["duration_s"] == 0


@pytest.mark.parametrize("step", [DemonstrationStep("click", target="menu"),
                                  DemonstrationStep("click", target="item"),
                                  DemonstrationStep("point", target="item")])
def test_menu_cannot_be_bypassed_with_direct_operations(step):
    with pytest.raises(ModelError, match=r"task\[task\]\.steps\[0\]\.target.*menu_select"):
        engine.predict(menu_project((step,)))


def test_menu_select_rejects_non_menu_target():
    with pytest.raises(ModelError, match=r"steps\[0\]\.target.*requires a menu_item"):
        validate_project(project((DemonstrationStep("menu_select", target="field"),)))


@pytest.mark.parametrize("parent", ["missing", "item"])
def test_menu_parent_must_be_existing_single_level_context_menu(parent):
    p = menu_project()
    frame = p.design.frames[0]
    frame = replace(frame, widgets=(frame.widgets[0], replace(frame.widgets[1], parent=parent)))
    with pytest.raises(ModelError, match=r"widgets\[1\]\.parent"):
        validate_project(replace(p, design=replace(p.design, frames=(frame,))))


def test_second_menu_selection_rejected_with_demonstration_context():
    with pytest.raises(ModelError, match=r"task\[task\]\.steps\[1\]\.op.*unsupported repeated menu selection"):
        engine.predict(menu_project((DemonstrationStep("menu_select", target="item"),) * 2))


def test_implementation_identity_is_separate_from_model_content_hash():
    p = project()
    result = engine.predict(p).data
    assert result["input_sha256"] == input_hash(p)
    assert "validation.py" in result["implementation"]["files"]
    expected = hashlib.sha256(json.dumps({
        "implementation_sha256": result["implementation"]["sha256"],
        "input_sha256": result["input_sha256"], "task_id": "task",
        "engine_version": result["engine"]["version"],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert result["execution_fingerprint"] == expected
