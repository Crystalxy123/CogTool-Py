"""Source-checked logical cases, independent of original execution evidence.

The expected sequences are written explicitly from the restricted rules in
KLMCognitiveGenerator.java and KeyboardUtil.java at the pinned commit.
"""
import pytest

from cogtool_py.generator import generate
from cogtool_py.models import Project


pytestmark = pytest.mark.independent


def widget(ident, kind="button", *, label=None, name=None, x=10, y=10):
    return {"id": ident, "name": name or ident, "label": ident if label is None else label,
            "kind": kind, "x": x, "y": y, "width": 20, "height": 20}


def project_for(steps, *, widgets=None, hand="mouse", mouse_hand="right", focus=None,
                other_frames=(), transitions=()):
    return Project.from_dict({
        "schema_version": 1, "id": "independent-generation", "name": "规则测试",
        "engine": "klm_baseline",
        "parameters": {name: {"value": value, "unit": "s", "source": "synthetic independent test"}
                       for name, value in {"click_s": 0.2, "key_s": 0.2, "homing_s": 0.6}.items()},
        "design": {"id": "d", "name": "D", "coordinate_unit": "px",
                   "frames": [{"id": "f", "name": "F", "widgets": widgets or [widget("a")]},
                              *other_frames], "transitions": list(transitions)},
        "tasks": [{"id": "task", "name": "T", "demonstration": {
            "initial": {"frame": "f", "mouse": [0, 0], "mouse_hand": mouse_hand,
                        "hand": hand, "focus": focus}, "steps": steps}}],
    })


def script_for(steps, **kwargs):
    project = project_for(steps, **kwargs)
    return generate(project, project.tasks[0])


def operations(script):
    return [step.op for step in script.steps]


def test_first_click_inserts_mental_point_and_preserves_ownership():
    script = script_for([{"op": "click", "target": "a"}])
    assert operations(script) == ["think", "point", "click"]
    assert [s.origin for s in script.steps] == ["automatic", "automatic", "demonstrated"]
    assert [s.demo_index for s in script.steps] == [0, 0, 0]
    assert script.steps[0].duration_s == 1.2
    assert "KLMCognitiveGenerator.java" in script.steps[0].source


def test_click_homes_mouse_hand_after_mental():
    script = script_for([{"op": "click", "target": "a"}], hand="keyboard")
    assert operations(script) == ["think", "home", "point", "click"]
    assert script.steps[1].device == "mouse"
    assert script.steps[1].state_before["hand"] == "keyboard"
    assert script.steps[1].state_after["hand"] == "mouse"


def test_explicit_think_suppresses_only_redundant_automatic_mental():
    script = script_for([{"op": "think", "duration_s": 0.4}, {"op": "click", "target": "a"}])
    assert operations(script) == ["think", "point", "click"]
    assert script.steps[0].origin == "demonstrated"
    assert script.steps[0].duration_s == 0.4


def test_two_explicit_thinks_are_not_deleted():
    script = script_for([{"op": "think", "duration_s": 0.4}, {"op": "think", "duration_s": 0.6}])
    assert operations(script) == ["think", "think"]
    assert [s.duration_s for s in script.steps] == [0.4, 0.6]


def test_repeat_click_does_not_repeat_mental_or_point():
    script = script_for([{"op": "click", "target": "a"}, {"op": "click", "target": "a"}])
    assert operations(script) == ["think", "point", "click", "click"]
    assert [s.demo_index for s in script.steps] == [0, 0, 0, 1]


def test_distinct_button_repeats_mental_and_point():
    script = script_for([{"op": "click", "target": "a"}, {"op": "click", "target": "b"}],
                        widgets=[widget("a"), widget("b", x=80)])
    assert operations(script) == ["think", "point", "click", "think", "point", "click"]


@pytest.mark.parametrize("first,second", [("SAVE", "done"), ("yes", "OK"), ("Cancel", "abort"), ("no", "quit")])
def test_same_terminator_group_suppresses_second_mental(first, second):
    # Terminator lists use name OR title, case-insensitively.
    script = script_for([{"op": "click", "target": "a"}, {"op": "click", "target": "b"}],
                        widgets=[widget("a", label=first), widget("b", label=second, x=80)])
    assert operations(script) == ["think", "point", "click", "point", "click"]


@pytest.mark.parametrize("first,second", [("save", "cancel"), ("save", "save as"), ("exit", "confirm")])
def test_different_terminator_groups_or_partial_words_need_mental(first, second):
    script = script_for([{"op": "click", "target": "a"}, {"op": "click", "target": "b"}],
                        widgets=[widget("a", label=first), widget("b", label=second, x=80)])
    assert operations(script) == ["think", "point", "click", "think", "point", "click"]


def test_same_bounds_suppress_point_but_different_identity_needs_mental():
    script = script_for([{"op": "click", "target": "a"}, {"op": "click", "target": "b"}],
                        widgets=[widget("a"), widget("b")])
    assert operations(script) == ["think", "point", "click", "think", "click"]


def test_identical_widget_fields_ignore_distinct_ids_for_mental():
    # Upstream isIdentical compares name/title/type/shape, not widget identity.
    script = script_for([{"op": "click", "target": "a"}, {"op": "click", "target": "b"}],
                        widgets=[widget("a", name="shared", label="same"),
                                 widget("b", name="shared", label="same")])
    assert operations(script) == ["think", "point", "click", "click"]


def test_point_alone_does_not_invent_think():
    script = script_for([{"op": "point", "target": "a"}, {"op": "click", "target": "a"}])
    assert operations(script) == ["point", "think", "click"]
    assert script.steps[0].origin == "demonstrated"


def test_redundant_point_is_reported_and_not_charged_again():
    script = script_for([{"op": "point", "target": "a"}, {"op": "point", "target": "a"}])
    assert operations(script) == ["point"]
    assert any("redundant point" in warning for warning in script.warnings)


@pytest.mark.parametrize("mouse_hand,keys,expected", [
    ("right", ["a", "s", " "], ["key", "key", "key"]),
    ("right", ["a", "j"], ["home", "key", "key"]),
    ("left", ["j", "k"], ["key", "key"]),
    ("left", ["j", "a"], ["home", "key", "key"]),
])
def test_keyboard_homes_only_for_keys_using_mouse_hand(mouse_hand, keys, expected):
    # The whole sequence is scanned: an eventual mouse-hand key homes before
    # the first normal key, even if that first key uses the other hand.
    script = script_for([{"op": "keys", "keys": keys}], widgets=[widget("field", "textbox")],
                        mouse_hand=mouse_hand, focus="field")
    assert operations(script) == expected
    assert [s.key for s in script.steps if s.op == "key"] == keys


@pytest.mark.parametrize("mouse_hand,key,expected", [
    ("right", "ENTER", ["think", "home", "key"]),
    ("right", "ESC", ["think", "key"]),
    ("left", "ENTER", ["think", "key"]),
    ("left", "ESC", ["think", "home", "key"]),
])
def test_command_key_think_precedes_required_homing(mouse_hand, key, expected):
    script = script_for([{"op": "keys", "keys": [key]}], widgets=[widget("field", "textbox")],
                        mouse_hand=mouse_hand, focus="field")
    assert operations(script) == expected


def test_repeated_commands_share_mental_but_changed_command_gets_one():
    script = script_for([{"op": "keys", "keys": ["ENTER", "ENTER", "BACKSPACE", "BACKSPACE"]}],
                        widgets=[widget("field", "textbox")], focus="field", hand="keyboard")
    assert operations(script) == ["think", "key", "key", "think", "key", "key"]


def test_command_repeat_state_persists_across_demo_segments():
    script = script_for([{"op": "keys", "keys": ["ENTER"]}, {"op": "keys", "keys": ["ENTER", "ESC"]}],
                        widgets=[widget("field", "textbox")], focus="field", hand="keyboard")
    assert operations(script) == ["think", "key", "key", "think", "key"]


def test_normal_key_breaks_command_repetition():
    script = script_for([{"op": "keys", "keys": ["ENTER", "a", "ENTER"]}],
                        widgets=[widget("field", "textbox")], focus="field", hand="keyboard")
    assert operations(script) == ["think", "key", "key", "think", "key"]


def test_textbox_click_sets_focus_then_keys_home_once():
    script = script_for([{"op": "click", "target": "field"}, {"op": "keys", "keys": ["a", "j"]},
                         {"op": "keys", "keys": ["k"]}], widgets=[widget("field", "textbox")])
    assert operations(script) == ["think", "point", "click", "home", "key", "key", "key"]
    assert script.steps[2].state_after["focus"] == "field"
    assert script.final_state["hand"] == "keyboard"


def test_explicit_look_at_is_documented_baseline_dwell_without_extra_think():
    script = script_for([{"op": "look_at", "target": "a", "duration_s": 0.4},
                         {"op": "click", "target": "a"}])
    assert operations(script) == ["look_at", "point", "click"]
    assert script.steps[0].duration_s == 0.4
    assert any("EMMA" in warning for warning in script.warnings)


def test_explicit_wait_remains_a_serial_step_and_resets_click_state():
    script = script_for([{"op": "click", "target": "a"}, {"op": "wait", "duration_s": 0.5},
                         {"op": "click", "target": "a"}])
    assert operations(script) == ["think", "point", "click", "wait", "think", "click"]
    assert script.steps[3].duration_s == 0.5


def test_transition_wait_commits_next_frame_after_response_barrier():
    script = script_for([
        {"op": "click", "target": "field", "transition": "go"},
        {"op": "point", "target": "b"},
    ], widgets=[widget("field", "textbox")], focus="field",
        other_frames=[{"id": "next", "name": "Next", "widgets": [widget("b", x=80)]}],
        transitions=[{"id": "go", "from_frame": "f", "target": "field", "to_frame": "next", "delay_s": 0.5}])
    assert operations(script) == ["think", "point", "click", "wait", "transition", "point"]
    assert script.steps[3].duration_s == 0.5
    assert script.steps[3].state_before["frame"] == "f"
    assert script.steps[3].state_after["frame"] == "f"
    assert script.steps[4].state_after["frame"] == "next"
    assert script.steps[4].state_after["focus"] is None
    assert script.steps[5].frame == "next"


def test_no_delay_does_not_create_phantom_wait():
    script = script_for([{"op": "click", "target": "a", "transition": "go"}],
                        other_frames=[{"id": "next", "name": "Next", "widgets": []}],
                        transitions=[{"id": "go", "from_frame": "f", "target": "a", "to_frame": "next", "delay_s": 0}])
    assert operations(script) == ["think", "point", "click", "transition"]
