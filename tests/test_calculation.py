"""Independent, hand-calculated evidence; no original CogTool output is used.

The numeric expectations below are analytic constants, not values obtained by
calling the implementation under test. See docs/model_semantics.md for sources.
"""
import math

import pytest

from cogtool_py.engine import point_time, predict
from cogtool_py.models import ParameterSet, Project, Widget


pytestmark = pytest.mark.independent


def parameters(**overrides):
    values = {"click_s": 0.2, "key_s": 0.2, "homing_s": 0.6, **overrides}
    return ParameterSet.parse({
        name: {"value": value,
               "unit": "px/in" if name == "pixels_per_inch" else "in" if name == "viewing_distance_in" else "s",
               "source": "independent synthetic test assumption, not a CogTool total duration"}
        for name, value in values.items()
    })


def rectangle(x, y, width, height):
    return Widget("target", "target", "Target", "button", x, y, width, height)


def test_visual_angles_are_converted_before_ratio():
    # 72 px/in * 15 in = 1080 px. atan(1080/1080)=45 degrees;
    # atan((1080*tan(15 degrees))/1080)=15 degrees, hence D/W=3.
    # .05 + .1*log2(3+.5) = .23073549220576042 seconds.
    width = 1080 * math.tan(math.pi / 12)
    target = rectangle(1080 - math.floor(width / 2), 0, width, 2)
    duration, _ = point_time((0, 1), target, parameters())
    assert duration == pytest.approx(0.23073549220576042, abs=1e-12)


def test_diagonal_30_by_40_rectangle_has_50_pixel_chord():
    # Target center (30,40), D=50, diagonal chord=50, angle ratio exactly 1.
    # With floor/initiation disabled, log2(1+.5)=.5849625007211562.
    target = rectangle(15, 20, 30, 40)
    duration, details = point_time((0, 0), target, parameters(
        fitts_coefficient_s=1.0, fitts_min_s=0.0, motor_initiation_s=0.0))
    assert duration == pytest.approx(0.5849625007211562, abs=1e-12)
    assert details["approach_width_px"] == pytest.approx(50.0, abs=1e-12)


def test_oblique_chord_is_not_projection_or_minimum_dimension():
    # Center (30,22.5), D=37.5. Unit direction=(.8,.6), so chord
    # min(30/.8,40/.6)=37.5. Projection would be 48; min dimension 30.
    target = rectangle(15, 2.5, 30, 40)
    duration, details = point_time((0, 0), target, parameters(
        fitts_coefficient_s=1.0, fitts_min_s=0.0, motor_initiation_s=0.0))
    assert details["approach_width_px"] == pytest.approx(37.5, abs=1e-12)
    assert duration == pytest.approx(0.5849625007211562, abs=1e-12)


@pytest.mark.parametrize("mouse,width", [((0, 40), 30.0), ((30, 0), 40.0)])
def test_axis_approach_uses_correct_dimension(mouse, width):
    _, details = point_time(mouse, rectangle(15, 20, 30, 40), parameters())
    assert details["approach_width_px"] == width


def test_minimum_fitts_applies_before_initiation():
    # Equal 20 px distance and width => raw .1*log2(1.5) < .1.
    duration, _ = point_time((0, 10), rectangle(10, 0, 20, 20), parameters())
    assert duration == pytest.approx(0.15, abs=1e-12)


def test_zero_distance_has_no_initiation_or_minimum_time():
    duration, _ = point_time((30, 40), rectangle(15, 20, 30, 40), parameters())
    assert duration == 0.0


def test_half_dimensions_follow_upstream_floor():
    target = rectangle(4.25, 9.5, 5, 7)
    assert target.center == (6.25, 12.5)
    duration, _ = point_time((6.25, 12.5), target, parameters())
    assert duration == 0.0


def test_pixels_and_density_scale_together_without_changing_angles():
    # Same physical display geometry represented at twice the pixel density.
    a, _ = point_time((0, 20), rectangle(1000, 0, 40, 40), parameters())
    b, _ = point_time((0, 40), rectangle(2000, 0, 80, 80), parameters(pixels_per_inch=144.0))
    assert b == pytest.approx(a, abs=1e-12)


def baseline_project(steps):
    return Project.from_dict({
        "schema_version": 1, "id": "independent-calculation", "name": "手算基线",
        "engine": "klm_baseline", "parameters": parameters().input_dict(),
        "design": {"id": "d", "name": "D", "coordinate_unit": "px",
                   "frames": [{"id": "f", "name": "F", "widgets": [{
                       "id": "field", "name": "field", "label": "输入框", "kind": "textbox",
                       "x": 10, "y": 10, "width": 20, "height": 20}]}], "transitions": []},
        "tasks": [{"id": "task", "name": "T", "demonstration": {
            "initial": {"frame": "f", "mouse": [0, 0], "mouse_hand": "right",
                        "hand": "keyboard", "focus": "field"}, "steps": steps}}],
    })


def test_serial_blocks_have_no_hidden_actr_component_charges():
    # .3 Think + .4 LookAt + .2 wait + 2*.2 keys + .6 home + 0 redundant home.
    project = baseline_project([
        {"op": "think", "duration_s": 0.3},
        {"op": "look_at", "target": "field", "duration_s": 0.4},
        {"op": "wait", "duration_s": 0.2},
        {"op": "keys", "keys": ["a", "j"]},
        {"op": "home", "device": "mouse"},
        {"op": "home", "device": "mouse"},
    ])
    result = predict(project).to_dict()
    assert result["predicted_time_s"] == pytest.approx(1.9, abs=1e-12)
    assert [e["start_s"] for e in result["events"]] == pytest.approx(
        [0.0, 0.3, 0.7, 0.9, 1.1, 1.3, 1.9], abs=1e-12)
    assert [e["end_s"] for e in result["events"]] == pytest.approx(
        [0.3, 0.7, 0.9, 1.1, 1.3, 1.9, 1.9], abs=1e-12)
    assert result["validation"]["original_comparison"] == "unverified"


def test_explicit_think_replaces_default_duration():
    result = predict(baseline_project([{"op": "think", "duration_s": 0.7}])).to_dict()
    assert result["predicted_time_s"] == pytest.approx(0.7, abs=1e-12)


def test_unspecified_think_uses_sourced_default():
    result = predict(baseline_project([{"op": "think"}])).to_dict()
    assert result["predicted_time_s"] == pytest.approx(1.2, abs=1e-12)


def test_transition_wait_is_measured_after_click_until_frame_commit():
    data = baseline_project([
        {"op": "click", "target": "field"},
    ]).to_dict()
    # Build the complete valid transition before the now-eager input validation.
    data["tasks"][0]["demonstration"]["steps"][0]["transition"] = "go"
    data["tasks"][0]["demonstration"]["initial"]["hand"] = "mouse"
    data["design"]["frames"] = list(data["design"]["frames"]) + [
        {"id": "next", "name": "Next", "widgets": []}]
    data["design"]["transitions"] = [{"id": "go", "from_frame": "f", "target": "field",
                                           "to_frame": "next", "delay_s": 0.5}]
    result = predict(Project.from_dict(data)).to_dict()
    # Center (20,20) and a 20x20 target yield D=W=sqrt(800), so pointing is
    # the .15 minimum; 1.2 Think + .15 point + .2 click + .5 response=2.05.
    assert result["predicted_time_s"] == pytest.approx(2.05, abs=1e-12)
    assert [e["op"] for e in result["events"]] == ["think", "point", "click", "wait", "transition"]
    assert result["events"][3]["start_s"] == pytest.approx(1.55, abs=1e-12)
    assert result["events"][3]["end_s"] == pytest.approx(2.05, abs=1e-12)
    assert result["events"][4]["start_s"] == pytest.approx(2.05, abs=1e-12)
    assert result["events"][4]["end_s"] == pytest.approx(2.05, abs=1e-12)
    assert result["final_state"]["frame"] == "next"
