"""Independent synthetic consequences of pinned motor rules, not accuracy tests.

Expected millisecond values below are hand-derived from the cited rule equations;
neither archived NP-B1 totals nor the function under test generate expectations.
"""
from dataclasses import FrozenInstanceError, replace
import json
import math
import subprocess
import sys

import pytest

from cogtool_py.engine import predict
from cogtool_py.io import input_hash, load_project, save_project
from cogtool_py.models import (Demonstration, DemonstrationStep, Design, Frame, InitialState,
                               ModelError, MOTOR_ENGINE, ParameterSet, Project, Task, Transition, Widget)
from cogtool_py.motor_subset import Movement, _Clock, changed_features, milliseconds

pytestmark = pytest.mark.independent


def make_project(steps=None, widgets=None, mouse=(0, 0)):
    parameters = ParameterSet.parse({key: {"value": value, "unit": "s", "source": "synthetic unused baseline assumption"}
                                     for key, value in {"click_s": .2, "key_s": .1, "homing_s": .4}.items()})
    return Project(2, "synthetic-motor", "Synthetic motor rule case", MOTOR_ENGINE,
                   parameters.with_motor_defaults(), Design("d", "d", "px", (Frame("f", "f", widgets or (
                       Widget("w", "w", "w", "textbox", -4, -5, 10, 10),)),), ()),
                   (Task("t", "t", Demonstration(InitialState("f", mouse, "right", "mouse", "w"),
                        steps if steps is not None else (DemonstrationStep("point", target="w"),))),))


def events(result, kind):
    return [e for e in result["events"] if e["event_type"] == kind]


def test_fresh_cursor_minimum_fitts_preparation_initiation_output_release():
    # D=1 px, width=10 px -> Fitts below the .100 s lower bound.
    # request0 + prep4, then initiation50/output150/finish200 relative to perform.
    r = predict(make_project()).data
    assert r["predicted_time_s"] == .204
    assert [(e["event_type"], e["start_s"], e["end_s"]) for e in r["events"]] == [
        ("motor_preparation", 0, .004), ("motor_initiation", .004, .054),
        ("cursor_move", .004, .154), ("cursor_finish", .004, .204)]
    assert r["events"][0]["details"]["features_to_prepare"] == 4
    changes = {e["trigger"]: e for e in r["state_changes"]}
    assert changes["perform_movement"]["after"]["motor_execution"] == "busy"
    assert changes["motor_initiation"]["after"]["motor_execution"] == "busy"
    assert changes["cursor_move"]["before"]["mouse"] == [0, 0]
    assert changes["cursor_move"]["after"]["mouse"] == [1, 0]
    assert changes["cursor_move"]["after"]["motor_execution"] == "busy"
    assert changes["cursor_finish"]["after"]["motor_execution"] == "free"
    assert sum(e["duration_s"] for e in r["events"]) > r["predicted_time_s"]


def click_project():
    w = Widget("w", "w", "w", "textbox", -5, -5, 10, 10)
    return make_project((DemonstrationStep("think", duration_s=0), DemonstrationStep("click", target="w"),
                         DemonstrationStep("click", target="w")), (w,))


def test_punch_fresh_three_features_then_preparation_reuse():
    # Zero-distance generated point does not prepare. First punch prep .003,
    # output .063 / release .153. Second reuses punch, ends .303 (not .306).
    r = predict(click_project()).data
    assert r["predicted_time_s"] == .303
    assert [e["duration_s"] for e in events(r, "motor_preparation")] == [.003, 0]
    assert [e["end_s"] for e in events(r, "click_output")] == [.063, .213]
    assert [e["end_s"] for e in events(r, "click_finish")] == [.153, .303]
    assert r["final_motor_state"]["last_prepared"]["style"] == "punch"
    assert r["final_motor_state"]["last_click"]["button"] == "left"


@pytest.mark.parametrize("previous,current,expected", [
    (None, Movement("cursor", 0, 0), 4), (None, Movement("punch"), 3),
    (Movement("punch"), Movement("cursor", 0, 0), 4),
    (Movement("cursor", 0, 0), Movement("punch"), 3),
    (Movement("punch"), Movement("punch"), 0),
    (Movement("cursor", 1, 0), Movement("cursor", 2.999, math.pi / 4 - .0001), 0),
    (Movement("cursor", 1, 0), Movement("cursor", 3, 0), 1),
    (Movement("cursor", 1, 0), Movement("cursor", 1, math.pi / 4), 1),
    (Movement("cursor", 1, 0), Movement("cursor", 3, math.pi / 4), 2),
    (Movement("cursor", 1, math.pi - .01), Movement("cursor", 1, -math.pi + .01), 1),
])
def test_source_feature_boundary_rules(previous, current, expected):
    assert changed_features(previous, current) == expected


def test_consecutive_cursor_width_not_a_preparation_feature_and_think_keeps_memory():
    widgets = (Widget("w", "w", "w", "textbox", -4, -5, 10, 10),
               Widget("b", "b", "b", "button", -8, -10, 20, 20))  # centers 1,0 and 2,0
    p = make_project((DemonstrationStep("point", target="w"), DemonstrationStep("think", duration_s=.2),
                      DemonstrationStep("point", target="b")), widgets)
    r = predict(p).data
    assert [e["duration_s"] for e in events(r, "motor_preparation")] == [.004, 0]
    assert r["predicted_time_s"] == .604  # 204 + 200 Think + 200 reused cursor


def test_cursor_feature_comparison_uses_angular_distance_not_pixels():
    widgets = (Widget("w", "w", "w", "textbox", -4, -5, 10, 10),
               Widget("b", "b", "b", "button", -3, -5, 10, 10),
               Widget("c", "c", "c", "button", 47, -5, 10, 10))
    r = predict(make_project(tuple(DemonstrationStep("point", target=k) for k in ("w", "b", "c")), widgets)).data
    # Distances 1,1,50 px: the final difference is >2 visual degrees, others equal.
    assert [e["details"]["features_to_prepare"] for e in events(r, "motor_preparation")] == [4, 0, 1]


def test_zero_distance_leaves_previous_preparation_unchanged():
    p = click_project()
    task = p.tasks[0]
    p = replace(p, tasks=(replace(task, demonstration=replace(task.demonstration,
        steps=task.demonstration.steps[:2] + (DemonstrationStep("point", target="b"), DemonstrationStep("click", target="w")))),),
        design=replace(p.design, frames=(replace(p.design.frames[0], widgets=p.design.frames[0].widgets + (
            Widget("b", "b", "b", "button", -10, -10, 20, 20),)),)))
    r = predict(p).data
    assert len(events(r, "cursor_noop")) == 3
    assert [e["duration_s"] for e in events(r, "motor_preparation")] == [.003, 0]


def test_each_relative_delay_rounds_once_and_same_time_priority_fifo():
    assert [milliseconds(s) for s in (.0005, .0015, .0025)] == [0, 2, 2]
    clock, observed = _Clock(), []
    clock.schedule(.001, lambda: observed.append("first"))
    clock.schedule(.001, lambda: observed.append("second"))
    clock.schedule(.001, lambda: observed.append("priority"), priority=10)
    clock.drain()
    assert observed == ["priority", "first", "second"]
    p = make_project()
    for name, value in {"motor_feature_prep_s": .000625, "fitts_min_s": .10049, "motor_initiation_s": .05049}.items():
        p = replace(p, parameters=p.parameters.override(name, value, source="synthetic quantization test"))
    # prep 2 ms; I rounds to50; I+F=150.98 rounds151; I+F+B rounds201.
    r = predict(p).data
    assert [e["end_s"] for e in r["events"]] == [.002, .052, .153, .203]


def test_queue_end_includes_output_even_if_unusual_parameters_release_first():
    p = click_project()
    p = replace(p, parameters=p.parameters.override("motor_key_closure_s", .2, source="synthetic queue boundary"))
    r = predict(p).data
    assert [e["end_s"] for e in events(r, "click_finish")] == [.153, .403]
    assert [e["end_s"] for e in events(r, "click_output")] == [.253, .503]
    assert r["predicted_time_s"] == .503  # all pending output drains; no early termination


@pytest.mark.parametrize("step", [DemonstrationStep("keys", keys=("a",)),
                                 DemonstrationStep("home", device="keyboard"),
                                 DemonstrationStep("look_at", target="w", duration_s=.1)])
def test_unsupported_steps_fail_without_baseline_fallback(step):
    with pytest.raises(ModelError, match=r"task\[t\].steps\[0\].*outside motor subset.*no baseline fallback"):
        predict(make_project((step,)))


def test_left_hand_or_initial_keyboard_rejected():
    p = make_project()
    for changes in ({"mouse_hand": "left"}, {"hand": "keyboard"}):
        task = p.tasks[0]
        bad = replace(p, tasks=(replace(task, demonstration=replace(task.demonstration,
                      initial=replace(task.demonstration.initial, **changes))),))
        with pytest.raises(ModelError, match="right hand already on mouse"):
            predict(bad)


def test_new_profile_reuses_immutable_parameters_roundtrip_hash_and_cli(tmp_path):
    p = make_project()
    assert p.parameters.with_motor_defaults() == p.parameters
    with pytest.raises(TypeError):
        p.parameters.entries["motor_burst_s"] = p.parameters.entries["motor_burst_s"]
    with pytest.raises(FrozenInstanceError):
        p.parameters.entries["motor_burst_s"].value = .1
    changed = replace(p, parameters=p.parameters.override("motor_burst_s", .1, source="synthetic override"))
    assert p.parameters.value("motor_burst_s") == .05
    assert predict(changed).data["predicted_time_s"] == .254
    assert input_hash(changed) != input_hash(p)
    ordered = replace(p, parameters=ParameterSet(dict(reversed(list(p.parameters.entries.items())))))
    assert input_hash(ordered) == input_hash(p)
    path = tmp_path / "input.json"
    save_project(changed, path)
    restored = load_project(path)
    assert restored == changed
    assert input_hash(restored) == input_hash(changed)
    assert predict(restored).data["events"] == predict(changed).data["events"]
    cli = subprocess.run([sys.executable, "-m", "cogtool_py", "predict", str(path), "--out", str(tmp_path / "out")], capture_output=True, text=True)
    assert cli.returncode == 0, cli.stderr
    result = json.loads((tmp_path / "out/result.json").read_text())
    assert result["events"] == predict(changed).data["events"]
    assert result["input_sha256"] == input_hash(changed)


@pytest.mark.parametrize("value,unit", [(-.1, "s"), (float("nan"), "s"), (.1, "ms"), (True, "s")])
def test_invalid_motor_overrides_rejected(value, unit):
    with pytest.raises(ModelError, match="motor_burst_s"):
        make_project().parameters.override("motor_burst_s", value, unit=unit, source="synthetic invalid override")


def test_explicit_profile_required_and_baseline_does_not_absorb_extra_parameters():
    p = make_project()
    core = ParameterSet({k: v for k, v in p.parameters.entries.items() if k not in
                         {"motor_feature_prep_s", "motor_burst_s", "motor_key_closure_s"}})
    with pytest.raises(ModelError, match="explicit complete motor profile"):
        predict(replace(p, parameters=core))
    with pytest.raises(ModelError, match="require the experimental engine"):
        predict(replace(p, engine="klm_baseline"))
    baseline = predict(replace(p, engine="klm_baseline", parameters=core)).data
    assert baseline["engine"]["name"] == "klm_baseline"
    assert len(baseline["parameters"]) == 9
    assert baseline["predicted_time_s"] == pytest.approx(.15)


def test_baseline_click_assumption_is_not_a_motor_subset_parameter():
    p = click_project()
    changed = replace(p, parameters=p.parameters.override("click_s", 7, source="unused baseline assumption test"))
    assert predict(changed).data["events"] == predict(p).data["events"]
    assert "click_s" in predict(p).data["unused_parameters"]


def test_distance_width_and_menu_geometry_have_formula_consistent_response():
    p = make_project(widgets=(Widget("w", "w", "w", "textbox", 95, -5, 10, 10),))
    def moved(x, width):
        w = replace(p.design.frames[0].widgets[0], x=x, width=width)
        return replace(p, design=replace(p.design, frames=(replace(p.design.frames[0], widgets=(w,)),)))
    base = predict(p).data
    farther = predict(moved(195, 10)).data  # centers100→200, same width
    wider = predict(moved(90, 20)).data     # center100 unchanged, double approach width
    assert farther["predicted_time_s"] > base["predicted_time_s"] > wider["predicted_time_s"]
    # Direct, independently written angular/Fitts equation for center100, width10.
    fitts = .1 * math.log2(math.atan(100 / 1080) / math.atan(10 / 1080) + .5)
    expected_ms = 4 + round((.05 + fitts + .05) * 1000)
    assert base["predicted_time_s"] == expected_ms / 1000


def test_menu_opens_and_selects_only_at_device_outputs_with_no_name_special_case():
    parent = Widget("w", "generic parent", "menu", "context_menu", 5, -5, 10, 10)
    item = Widget("item", "arbitrary item", "choice", "menu_item", 15, -5, 10, 10, "w")
    p = make_project((DemonstrationStep("menu_select", target="item"),), (parent, item))
    task = p.tasks[0]
    p = replace(p, tasks=(replace(task, demonstration=replace(task.demonstration,
                           initial=replace(task.demonstration.initial, focus=None))),))
    r = predict(p).data
    outputs = events(r, "click_output")
    assert [e["details"]["button"] for e in outputs] == ["right", "left"]
    assert outputs[0]["state_before"]["open_menu"] is None
    assert outputs[0]["state_after"]["open_menu"] == "w"
    assert outputs[1]["state_before"]["open_menu"] == "w"
    assert outputs[1]["state_after"]["open_menu"] is None
    assert [e["details"]["features_to_prepare"] for e in events(r, "motor_preparation")] == [4, 3, 4, 3]
    renamed = replace(p, id="not-an-official-case", name="unrelated", tasks=(replace(p.tasks[0], id="other", name="other"),))
    assert predict(renamed).data["predicted_time_s"] == r["predicted_time_s"]
    assert r["predicted_time_s"] == 1.914  # 204+153+1200+204+153 ms, minimum-Fitts geometry


def test_zero_time_parameters_preserve_event_order_and_release_resources():
    p = make_project()
    for name in ("motor_feature_prep_s", "motor_initiation_s", "motor_burst_s", "fitts_min_s", "fitts_coefficient_s"):
        p = replace(p, parameters=p.parameters.override(name, 0, source="synthetic simultaneous events"))
    r = predict(p).data
    assert r["predicted_time_s"] == 0
    assert [e["event_type"] for e in sorted(r["events"], key=lambda e: e["completion_order"])] == [
        "motor_preparation", "motor_initiation", "cursor_move", "cursor_finish"]
    assert all(r["final_motor_state"][field] == "free" for field in
               ("motor_preparation", "motor_processor", "motor_execution"))


def test_frame_change_is_explicitly_outside_experimental_scope():
    p = make_project((DemonstrationStep("click", target="w", transition="next"),))
    p = replace(p, design=replace(p.design, frames=p.design.frames + (Frame("next", "next", ()),),
                                 transitions=(Transition("next", "f", "w", "next", 0),)))
    with pytest.raises(ModelError, match="self-loop transitions only"):
        predict(p)
