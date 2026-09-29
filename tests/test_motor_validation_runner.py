"""Synthetic checks for validation bookkeeping; no model accuracy claims."""
from dataclasses import replace

import pytest

from cogtool_py.models import Demonstration, DemonstrationStep, Design, Frame, InitialState, ParameterSet, Project, Task, Widget
from scripts.run_motor_validation import synthetic_variants, verify_result

pytestmark = pytest.mark.independent


def test_overlapping_intervals_are_checked_against_final_end_not_duration_sum():
    result = {"engine": {"name": "experimental"}, "implementation": {"sha256": "code"},
              "predicted_time_s": .3, "events": [
                  {"event_id": "a", "start_s": 0, "end_s": .3, "duration_s": .3, "dependencies": []},
                  {"event_id": "b", "start_s": .1, "end_s": .2, "duration_s": .1, "dependencies": []},
              ]}
    assert verify_result(result, "experimental", "code") == []
    assert verify_result({**result, "predicted_time_s": .4}, "experimental", "code")


def test_missing_duration_and_wrong_identity_are_not_accepted_as_zero():
    result = {"engine": {"name": "wrong"}, "implementation": {"sha256": "old"},
              "predicted_time_s": 0, "events": [{"index": 0, "start_s": 0, "end_s": 0, "duration_s": None}]}
    issues = verify_result(result, "expected", "current")
    assert len(issues) == 3
    assert "unexpected engine identity" in issues


def test_geometry_variants_are_distinct_synthetic_cases_and_preserve_original():
    parameters = ParameterSet.parse({name: {"value": .2, "unit": "s", "source": "synthetic"}
                                     for name in ("click_s", "key_s", "homing_s")})
    parent = Widget("w8", "parent", "", "context_menu", 20, 302, 88, 23)
    item = Widget("w22", "item", "", "menu_item", 64, 345.5, 119, 15.75, "w8")
    project = Project(2, "synthetic", "Synthetic", "klm_baseline", parameters,
                      Design("d", "D", "px", (Frame("f", "F", (parent, item)),), ()),
                      (Task("t", "T", Demonstration(InitialState("f", (0, 0), "right", "mouse", None),
                                                    (DemonstrationStep("menu_select", target="w22"),))),))
    variants = synthetic_variants(project)
    assert len(variants) == 3
    assert project.design.frames[0].widgets == (parent, item)
    large_parent, large_item = variants["larger_targets"].design.frames[0].widgets
    assert large_parent.center == parent.center
    assert large_item.center == item.center
    assert large_parent.width == parent.width * 2
    assert variants["farther_parent"].design.frames[0].widgets[0].x == parent.x + 200
    assert variants["displaced_item"].design.frames[0].widgets[0] == parent
    assert variants["displaced_item"].design.frames[0].widgets[1].x == item.x + 80
