"""Independent counterexamples for declared cross-page/key/delay mappings."""
from copy import deepcopy

import pytest

from scripts.compare_java_task import map_java_steps, map_python_steps, map_demonstrations

pytestmark = pytest.mark.independent


def project():
    return {
        "design": {
            "frames": [
                {"id": "a", "name": "A", "widgets": [{"id": "a:button", "name": "Same"}]},
                {"id": "b", "name": "B", "widgets": [{"id": "b:button", "name": "Same"}]},
            ],
            "transitions": [{"id": "t", "from_frame": "a", "to_frame": "b",
                             "target": "a:button", "delay_s": 0.5, "delay_label": "response"}],
        },
        "tasks": [{"demonstration": {
            "initial": {"frame": "a", "mouse_hand": "right", "hand": "keyboard"},
            "steps": [{"op": "keys", "device": "keyboard", "keys": ["a", "j"]}],
        }}],
    }


def js(kind, *, action=None, focus=None, origin=True, **extra):
    step = {"class": "original." + kind, "owner_demonstration_index": 0,
            "inserted_by_user": origin, "frame": "A", "destination": "A", "focus": focus}
    if action:
        step["action"] = action
    step.update(extra)
    return {"step": step, "state": {"real_observation": "retained"}}


def ps(op, *, key=None, target=None, origin="demonstrated", **extra):
    step = {"op": op, "frame": "a", "demo_index": 0, "origin": origin, "key": key,
            "target": target, "duration_s": None, "device": "keyboard" if op == "key" else None}
    step.update(extra)
    return step


def key_rows(keys):
    return {"steps": [ps("key", key=key) for key in keys]}


def test_text_segment_records_positions_and_cannot_hide_missing_or_swapped_key():
    j, witnesses, _, unresolved = map_java_steps([js("TextActionSegment", text="aj")])
    assert not unresolved
    assert [w["character_index"] for w in witnesses] == [0, 1]
    assert [w["segment_text"] for w in witnesses] == ["aj", "aj"]
    p, *_ = map_python_steps(project(), key_rows(["a", "j"]))
    assert j == p
    for corrupted in (["a"], ["j", "a"], ["a", "j", "j"]):
        p, *_ = map_python_steps(project(), key_rows(corrupted))
        assert j != p


def test_unsupported_segment_is_preserved_as_unmapped():
    raw = js("TextActionSegment", text="CTRL+C")
    rows, _, _, unresolved = map_java_steps([raw])
    assert rows == []
    assert unresolved[0]["raw"] == raw


def test_keyboard_demo_cannot_hide_command_or_press_kind():
    model = project()
    action = {"class": "original.KeyAction", "text": "aj", "is_command": False,
              "modifiers": 0, "press_type": "Type"}
    raw = js("ActionScriptStep", action=action, focus="Keyboard")["step"]
    j, p, unmapped, _ = map_demonstrations(model, {"steps": [raw]})
    assert not unmapped and j == p
    for key, value in (("is_command", True), ("modifiers", 1), ("press_type", "Down")):
        bad = deepcopy(raw)
        bad["action"][key] = value
        j, p, unmapped, _ = map_demonstrations(model, {"steps": [bad]})
        # Commands are now an admitted action property, distinct from a
        # modifier. A mapped disagreement must remain visible; unsupported
        # press kinds must still retain their original unmapped evidence.
        assert unmapped or j != p
        if key == "press_type":
            assert unmapped and unmapped[0]["raw"] == bad
        else:
            assert not unmapped
            assert j[0][key] == value and p[0][key] != value
    command_model = deepcopy(model)
    command_model["tasks"][0]["demonstration"]["steps"][0]["is_command"] = True
    command_raw = deepcopy(raw)
    command_raw["action"]["is_command"] = True
    j, p, unmapped, _ = map_demonstrations(command_model, {"steps": [command_raw]})
    assert not unmapped and j == p
    assert j[0]["is_command"] is True and j[0]["modifiers"] == 0


def delay_case():
    model = project()
    model["tasks"][0]["demonstration"]["steps"] = [{"op": "click", "target": "a:button", "transition": "t"}]
    click = js("TransitionScriptStep", focus="Same", destination="B",
               transition={"source": "Same", "destination": "B", "delay_s": 0.5, "delay_label": "response",
                           "action": {"class": "original.ButtonAction", "button": "Left", "press_type": "Click"}})
    delay = js("TransitionDelayScriptStep", origin=False, duration_s=0.5, delay_label="response")
    steps = [
        ps("click", target="a:button"),
        ps("wait", origin="automatic", duration_s=0.5),
        ps("transition", origin="automatic", duration_s=0.0, note="t",
           state_before={"frame": "a"}, state_after={"frame": "b"}),
    ]
    return model, [click, delay], {"steps": steps}


def test_wait_duration_label_and_trigger_position_are_compared():
    model, java, result = delay_case()
    j, _, jc, ju = map_java_steps(java)
    p, _, pc, _, pu = map_python_steps(model, result)
    assert not ju and not pu and j == p and jc == pc
    wrong = deepcopy(result)
    wrong["steps"][1]["duration_s"] = 1.0
    assert map_python_steps(model, wrong)[0] != j
    wrong_model = deepcopy(model)
    wrong_model["design"]["transitions"][0]["delay_label"] = "different response"
    assert map_python_steps(wrong_model, result)[0] != j
    early = {"steps": [result["steps"][0], result["steps"][2], result["steps"][1]]}
    assert map_python_steps(model, early)[2] != jc


def test_duplicate_wait_or_missing_commit_is_detected():
    model, java, result = delay_case()
    j, _, jc, _ = map_java_steps(java)
    doubled = {"steps": result["steps"][:2] + [result["steps"][1]] + result["steps"][2:]}
    assert map_python_steps(model, doubled)[0] != j
    missing = {"steps": result["steps"][:-1]}
    assert map_python_steps(model, missing)[2] != jc


def test_same_widget_name_on_other_frame_is_not_the_same_target():
    model, _, result = delay_case()
    result["steps"][0]["target"] = "b:button"
    assert map_python_steps(model, result)[4]


def test_missing_destination_page_is_not_comparable():
    model, _, result = delay_case()
    model["design"]["frames"].pop()
    assert map_python_steps(model, result)[4]


def test_home_hand_and_device_are_not_discarded():
    j, _, _, _ = map_java_steps([js("ActionScriptStep", origin=False,
        action={"class": "original.HomeAction", "home_target": "Keyboard", "hand": "right"})])
    result = {"steps": [ps("home", origin="automatic", device="keyboard")]}
    model = project()
    p, *_ = map_python_steps(model, result)
    assert p == j
    result["steps"][0]["device"] = "mouse"
    assert map_python_steps(model, result)[0] != j
    result["steps"][0]["device"] = "keyboard"
    model["tasks"][0]["demonstration"]["initial"]["mouse_hand"] = "left"
    assert map_python_steps(model, result)[0] != j


def test_unknown_operation_never_silently_vanishes():
    model = project()
    rows, _, _, _, unresolved = map_python_steps(model, {"steps": [ps("hover")]})
    assert rows == [] and unresolved[0]["raw"]["op"] == "hover"
