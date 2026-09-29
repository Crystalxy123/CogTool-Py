"""Independent 2014 keyboard/hand consequences; synthetic, not original accuracy."""
from dataclasses import replace
import math

import pytest

from cogtool_py.generator import ScriptStep
from cogtool_py.models import ModelError
from cogtool_py.motor_subset import Clock, MotorModule, Movement, changed_features
from test_motor_subset import make_project

pytestmark = pytest.mark.independent


def module(hand="keyboard"):
    p = make_project()
    task = p.tasks[0]
    task = replace(task, demonstration=replace(task.demonstration,
                    initial=replace(task.demonstration.initial, hand=hand)))
    p = replace(p, parameters=p.parameters.with_keyboard_defaults(), tasks=(task,))
    return MotorModule(p, task, Clock())


def step(op="key", key="a", device=None, index=0):
    return ScriptStep(index, op, "demonstrated", index, "f", "w" if op == "key" else None,
                      key if op == "key" else None, None, device, "synthetic test", "",
                      {"frame": "f", "focus": "w"}, {"frame": "f", "focus": "w"})


def by_kind(m, kind):
    return [e for e in m.events if e["event_type"] == kind]


def test_home_row_punch_and_nonhome_peck_have_distinct_output_release():
    punch = module()
    punch.request(step(key="a"))
    punch.clock.drain()
    assert by_kind(punch, "motor_preparation")[0]["details"]["features_to_prepare"] == 3
    assert by_kind(punch, "key_output")[0]["end_s"] == .063
    assert by_kind(punch, "key_finish")[0]["end_s"] == .153
    peck = module()
    peck.request(step(key="q"))
    peck.clock.drain()
    assert by_kind(peck, "motor_preparation")[0]["details"]["features_to_prepare"] == 5
    assert by_kind(peck, "key_output")[0]["end_s"] == .155
    assert by_kind(peck, "key_finish")[0]["end_s"] == .305
    assert peck.state["hand_locations"] == {"left": [4, 4], "right": [7, 4]}
    assert peck.state["last_key"]["coordinates"] == [1, 3]


def test_alternating_hand_prepares_while_execution_busy_but_fifo_executes():
    m = module()
    first = m.request(step(key="a"))
    second = {}
    m.clock.schedule(.05, lambda: second.update(m.request(step(key="j", index=1))))
    m.clock.drain()
    assert first["completed"]
    assert [e["duration_s"] for e in by_kind(m, "motor_preparation")] == [.003, .002]
    assert [(e["start_s"], e["end_s"]) for e in by_kind(m, "key_output")] == [(.003, .063), (.153, .213)]
    assert [e["end_s"] for e in by_kind(m, "key_finish")] == [.153, .303]
    assert m.active_request is None
    assert m.manual_state == "free"


def test_key_preparation_busy_rejects_without_discarding_first_request():
    m = module()
    m.request(step(key="q"))
    with pytest.raises(ModelError, match="already being prepared"):
        m.request(step(key="j", index=1))
    m.clock.drain()
    assert len(by_kind(m, "key_output")) == 1
    assert m.state["last_key"]["requested_key"] == "q"


def test_homing_uses_keyboard_grid_fitts_and_changes_hand_at_output():
    m = module("mouse")
    old_mouse = list(m.state["mouse"])
    m.request(step("home", device="keyboard"))
    # hypot(21,2), width 4: F=.1*log2(D/4+.5); fresh PLY prep .004.
    fitts = max(.1, .1 * math.log2(math.hypot(21, 2) / 4 + .5))
    out = .004 + round((.05 + fitts) / .001) / 1000
    end = .004 + round((.05 + fitts + .05) / .001) / 1000
    assert m.state["hand_locations"]["right"] == [28, 2]
    m.clock.drain()
    assert by_kind(m, "hand_move")[0]["end_s"] == pytest.approx(out)
    assert by_kind(m, "hand_finish")[0]["end_s"] == pytest.approx(end)
    assert m.state["hand_locations"]["right"] == [7, 4]
    assert m.state["mouse"] == old_mouse
    assert m.state["hand"] == "keyboard"
    m.request(step("home", device="mouse", index=1))
    m.clock.drain()
    assert m.state["hand_locations"]["right"] == [28, 2]
    assert m.state["hand"] == "mouse"


def test_left_key_can_queue_behind_home_and_right_key_uses_posthome_location():
    m = module("mouse")
    m.request(step("home", device="keyboard"))
    m.clock.schedule(.05, lambda: m.request(step(key="a", index=1)))
    m.clock.schedule(.06, lambda: m.request(step(key="j", index=2)))
    m.clock.drain()
    assert [e["details"]["coordinates"] for e in by_kind(m, "key_output")] == [[1, 4], [7, 4]]
    assert [e["details"]["requested_key"] for e in by_kind(m, "key_output")] == ["a", "j"]
    assert len(by_kind(m, "hand_move")) == 1
    assert m.manual_state == "free"


def test_key_profile_is_explicit_and_does_not_mutate_mouse_parameters():
    old = make_project().parameters
    extended = old.with_keyboard_defaults()
    assert set(extended.entries) - set(old.entries) == {"motor_peck_fitts_coefficient_s"}
    assert all(extended.entries[k] == p for k, p in old.entries.items())
    assert extended.with_keyboard_defaults() == extended
    assert type(extended).parse(extended.input_dict(), schema_version=2) == extended
    p = make_project()
    m = MotorModule(p, p.tasks[0])
    with pytest.raises(ModelError, match="outside motor subset"):
        m.request(step())


def test_actual_java_aliases_and_unknown_keys_fail_without_baseline():
    from cogtool_py.motor_subset import key_command
    assert key_command("=")["backend_key"] == "hyphen"
    assert key_command("[")["backend_key"] == "P"
    assert key_command("]")["backend_key"] == "P"
    assert key_command("ENTER")["backend_key"] == "return"
    for unsupported in ("你", "A", "SHIFT", "Ctrl+A", "F1"):
        with pytest.raises(ModelError):
            key_command(unsupported)


def test_keyboard_feature_style_and_finger_differences_are_source_based():
    assert changed_features(None, Movement("peck_recoil", 1, 0, "left", "index")) == 5
    assert changed_features(Movement("punch", hand="left", finger="pinkie"),
                            Movement("punch", hand="right", finger="index")) == 2
    assert changed_features(Movement("punch", hand="left", finger="pinkie"),
                            Movement("punch", hand="left", finger="index")) == 1
    assert changed_features(Movement("cursor", 5, .1), Movement("home", 5, .1)) == 0
    assert changed_features(Movement("peck_recoil", 1, 0, "left", "index"),
                            Movement("peck_recoil", 1, 0, "right", "index")) == 4


def test_peck_parameter_override_has_formula_effect_without_using_key_block():
    m = module()
    m.parameters = m.parameters.override("motor_peck_fitts_coefficient_s", .2, source="synthetic formula")
    m.request(step(key="q"))
    m.clock.drain()
    movement = .2 * math.log2(1.5)
    assert by_kind(m, "key_output")[0]["end_s"] == pytest.approx(.005 + round((.05 + movement) / .001) / 1000)
    assert by_kind(m, "key_finish")[0]["end_s"] == pytest.approx(.005 + round((.05 + 2 * movement + .05) / .001) / 1000)


def test_redundant_home_retains_source_keyboard_and_mouse_asymmetry():
    # Upstream hand-to-home compares distinct vectors with EQUAL; it still
    # issues a zero-distance PLY. hand-to-mouse uses coordinate-wise VPT=.
    m = module("keyboard")
    m.request(step("home", device="keyboard"))
    m.clock.drain()
    assert by_kind(m, "hand_move")[0]["end_s"] == .154
    assert by_kind(m, "hand_finish")[0]["end_s"] == .204
    mouse = module("mouse")
    mouse.request(step("home", device="mouse"))
    mouse.clock.drain()
    assert [e["event_type"] for e in mouse.events] == ["hand_noop"]
    assert mouse.last_prepared is None


def test_late_key_output_is_retained_after_execution_release():
    m = module()
    m.parameters = m.parameters.override("motor_key_closure_s", .2, source="synthetic late key output")
    handle = m.request(step(key="a"))
    m.clock.schedule(.2, lambda: None)
    while m.clock.queue and m.clock.queue[0][0] <= 200:
        m.clock.step()
    assert m.manual_state == "free"
    assert not handle["completed"]
    assert m.active_request is handle
    m.clock.drain()
    assert by_kind(m, "key_output")[0]["end_s"] == .253
    assert handle["completed"]
    assert m.active_request is None


def test_keyboard_parameter_without_motor_profile_is_rejected():
    from cogtool_py.models import KEYBOARD_DEFAULTS, MOTOR_DEFAULTS, ParameterSet
    p = make_project().parameters
    entries = {key: value for key, value in p.entries.items() if key not in MOTOR_DEFAULTS}
    with pytest.raises(ModelError, match="keyboard profile requires"):
        ParameterSet({**entries, **KEYBOARD_DEFAULTS})
