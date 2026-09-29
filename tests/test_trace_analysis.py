"""Independent synthetic parser contracts; historical values are audited separately."""
from pathlib import Path
import json

import pytest

from scripts.analyze_npb1_trace import (
    TraceError, analyze, difference_table, integrity, link_motor, pair_productions, parse_trace, semantic_alignment,
)

pytestmark = pytest.mark.independent


def events(text):
    return parse_trace(text)["events"]


def test_unknown_lines_and_line_endings_are_lossless():
    text = "unknown\r\n:MOTOR module\n:MIN-FITTS-TIME 0.1 default: 0.2 : description\n\n 0.000 MOTOR mystery\nend without newline"
    parsed = parse_trace(text)
    assert "".join(line["raw"] for line in parsed["raw_lines"]) == text
    assert parsed["raw_lines"][0]["kind"] == "unknown"
    assert parsed["raw_lines"][-1]["raw"] == "end without newline"
    parameter = parsed["parameters"][0]
    assert parameter["observed"] == .1
    assert parameter["default"] == .2
    assert parameter["source"]["line_number"] == 3
    assert parameter["module"] == "MOTOR"


def test_lisp_parameter_forms_are_preserved_not_evaluated():
    parameter = parse_trace(":SEED (1 0) default: NO-DEFAULT : seed\n")["parameters"][0]
    assert parameter["observed"] == "(1 0)"
    assert parameter["default"] == "NO-DEFAULT"


def test_point_events_do_not_get_adjacent_durations():
    parsed = events("0.000 MOTOR FIRST\n0.500 VISION SECOND\n1.000 MOTOR THIRD\n")
    assert [event["timestamp_s"] for event in parsed] == [0, .5, 1]
    assert all(event["duration_s"] is None for event in parsed)


def test_same_name_production_pair_ignores_interleaved_events():
    paired = pair_productions(events("0.100 PROCEDURAL PRODUCTION-SELECTED THINK-7\n"
                                    "0.200 VISION SOMETHING\n1.300 PROCEDURAL PRODUCTION-FIRED THINK-7\n"))
    assert paired["pairs"][0]["duration_s"] == 1.2
    assert paired["pairs"][0]["selected_event_id"] == "L1"
    assert paired["pairs"][0]["fired_event_id"] == "L3"
    assert paired["unmatched"] == []


@pytest.mark.parametrize("text", [
    "0.0 PROCEDURAL PRODUCTION-SELECTED A\n0.1 PROCEDURAL PRODUCTION-FIRED B\n",
    "0.0 PROCEDURAL PRODUCTION-SELECTED A\n0.1 PROCEDURAL PRODUCTION-SELECTED A\n0.2 PROCEDURAL PRODUCTION-FIRED A\n",
    "0.2 PROCEDURAL PRODUCTION-SELECTED A\n0.1 PROCEDURAL PRODUCTION-FIRED A\n",
])
def test_wrong_duplicate_or_reverse_production_pairs_stay_unmatched(text):
    result = pair_productions(events(text))
    assert result["pairs"] == []
    assert len(result["unmatched"]) == len(text.splitlines())


def test_prepare_click_during_move_does_not_steal_move_finish():
    result = link_motor(events(
        '0.100 MOTOR MOVE-CURSOR OBJECT NIL LOC A "Parent in F" NIL\n'
        '0.104 MOTOR PREPARATION-COMPLETE\n0.154 MOTOR INITIATION-COMPLETE\n'
        '0.160 MOTOR PREPARE PUNCH HAND RIGHT FINGER INDEX\n0.163 MOTOR PREPARATION-COMPLETE\n'
        '0.300 MOTOR MOVE-CURSOR-ABSOLUTE #(1 2)\n0.350 MOTOR FINISH-MOVEMENT\n'
        '0.400 MOTOR CLICK-MOUSE NIL\n0.400 MOTOR PREPARATION-COMPLETE\n'
        '0.450 MOTOR INITIATION-COMPLETE\n0.460 MOTOR OUTPUT-KEY #(28 2)\n0.550 MOTOR FINISH-MOVEMENT\n'))
    move, prepare, click = result["actions"]
    assert move["phase_events"]["finish"] == "L7"
    assert prepare["phase_events"] == {"request": "L4", "preparation_complete": "L5"}
    assert click["phase_events"]["finish"] == "L12"
    assert click["prior_preparation_action_id"] == prepare["action_id"]
    assert click["button_from_trace"] is None
    assert result["unmatched"] == []
    assert all(action["duration_s"] is None for action in result["actions"])


def test_ambiguous_motor_execution_is_not_assigned_a_finish():
    result = link_motor(events('0.1 MOTOR MOVE-CURSOR OBJECT NIL LOC A "A" NIL\n'
                              '0.2 MOTOR PREPARATION-COMPLETE\n'
                              '0.3 MOTOR MOVE-CURSOR OBJECT NIL LOC B "B" NIL\n'
                              '0.4 MOTOR INITIATION-COMPLETE\n0.5 MOTOR FINISH-MOVEMENT\n'))
    assert result["actions"][0]["status"] == "ambiguous_overlapping_execution"
    assert "finish" not in result["actions"][0]["phase_events"]
    assert {item["event_id"] for item in result["unmatched"]} >= {"L3", "L4", "L5"}


def complete_trace():
    return ("0.000 PROCEDURAL CONFLICT-RESOLUTION\n"
            "2.495 PROCEDURAL PRODUCTION-SELECTED STOP-19\n"
            "2.495 PROCEDURAL PRODUCTION-FIRED STOP-19\n"
            "2.645 MOTOR FINISH-MOVEMENT\n"
            "2.645 ------ Stopped because no events left to process\n2.6450002\n")


def test_stop_motor_finish_and_cached_time_are_distinct_boundaries():
    result = integrity(parse_trace(complete_trace()), {"cached_prediction_s": 2.6450002})
    assert result["task_stop_events"][0]["timestamp_s"] == 2.495
    assert result["last_motor_finish"]["timestamp_s"] == 2.645
    assert result["cached_prediction_s"] == 2.6450002
    checks = {row["name"]: row for row in result["checks"]}
    assert checks["trace_end_vs_archived_cache"]["absolute_difference_s"] == 2e-7
    assert checks["trace_end_vs_archived_cache"]["status"] == "consistent"
    assert result["equivalence_evaluated"] is False


def test_missing_cache_is_not_treated_as_zero_or_consistent():
    checks = {row["name"]: row for row in integrity(parse_trace(complete_trace()), {})["checks"]}
    assert checks["trace_end_vs_archived_cache"]["status"] == "not_evaluated"
    assert checks["final_scalar_vs_archived_cache"]["second"] is None


def test_mismatched_cache_and_backward_timestamps_fail_integrity():
    parsed = parse_trace(complete_trace().replace("2.495 PROCEDURAL PRODUCTION-FIRED", "2.400 PROCEDURAL PRODUCTION-FIRED"))
    result = integrity(parsed, {"cached_prediction_s": 3.0})
    assert result["has_inconsistency"] is True
    assert {check["name"] for check in result["checks"] if check["status"] == "inconsistent"} >= {"timestamp_order", "trace_end_vs_archived_cache"}


def test_alignment_is_many_to_one_and_unmatched_events_remain():
    parsed = parse_trace("0.1 PROCEDURAL PRODUCTION-SELECTED FIND-2\n"
                         "0.2 PROCEDURAL PRODUCTION-FIRED FIND-2\n0.3 VISION UNKNOWN-VISUAL-COMPLETION\n")
    baseline = {"steps": [{"index": 0, "op": "point", "target": "w8"}],
                "events": [{"index": 0, "step_index": 0, "start_s": 0, "end_s": .4, "duration_s": .4}]}
    metadata = {"saved_generated_steps": [{"target": {"object_id": "8", "name": "Parent"}, "action": {"class": "MoveMouseAction"}}]}
    result = semantic_alignment(parsed, pair_productions(parsed["events"]), link_motor(parsed["events"]), metadata, baseline)
    anchor = result["anchors"][0]
    assert anchor["reference_event_ids"] == ["L1", "L2"]
    assert len(anchor["baseline_events"]) == 1
    assert anchor["reference_duration_s"] is None
    assert result["unmatched_reference_events"][0]["event_id"] == "L3"
    assert result["unmatched_python_events"]["experimental"] is None
    assert result["time_origin_shift_s"] == 0


def test_analyzer_baseline_only_retains_inputs_and_refuses_overwrite(tmp_path):
    trace = tmp_path / "trace.txt"
    trace.write_text(complete_trace())
    metadata = tmp_path / "archived_reference.json"
    metadata.write_text(json.dumps({"cached_prediction_s": 2.6450002, "source_object_id": "307"}))
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"predicted_time_s": 2.2, "events": [], "steps": []}))
    out = tmp_path / "analysis"
    result = analyze(trace, baseline, out)
    assert result["experimental_total_s"] is None
    assert result["reference_kind"] == "archived_reference"
    assert result["reference_attributes"] is None
    assert (out / "reference_trace.txt").read_bytes() == trace.read_bytes()
    assert len(json.loads((out / "raw_lines.json").read_text())) == len(complete_trace().splitlines())
    with pytest.raises(TraceError, match="already exists"):
        analyze(trace, baseline, out)


def test_motor_boundary_comparison_uses_corresponding_endpoints_without_summing():
    parsed = parse_trace('0.100 MOTOR MOVE-CURSOR OBJECT NIL LOC A "Parent in F" NIL\n'
                         '0.104 MOTOR PREPARATION-COMPLETE\n0.154 MOTOR INITIATION-COMPLETE\n'
                         '0.400 MOTOR MOVE-CURSOR-ABSOLUTE #(1 2)\n0.450 MOTOR FINISH-MOVEMENT\n')
    metadata = {"saved_generated_steps": [{"target": {"object_id": "8", "name": "Parent"},
                                          "action": {"class": "MoveMouseAction"}}]}
    baseline = {"steps": [{"index": 0, "op": "point", "target": "w8"}],
                "events": [{"step_index": 0, "start_s": 0, "end_s": .3, "duration_s": .3}]}
    experimental = {"steps": baseline["steps"], "events": [
        {"event_id": kind, "step_index": 0, "event_type": kind, "start_s": start, "end_s": end, "duration_s": end - start}
        for kind, start, end in [("motor_preparation", 0, .004), ("motor_initiation", .004, .054),
                                 ("cursor_move", .004, .304), ("cursor_finish", .004, .354)]]}
    aligned = semantic_alignment(parsed, pair_productions(parsed["events"]), link_motor(parsed["events"]), metadata, baseline, experimental)
    phases = {item["phase"]: item for item in aligned["anchors"][0]["motor_phase_timepoint_comparison"]}
    assert phases["output"]["experimental_timestamp_s"] == .304
    assert phases["output"]["experimental_minus_reference_s"] == pytest.approx(-.096)
    assert phases["finish"]["experimental_timestamp_s"] == .354
    assert phases["finish"]["baseline_timestamp_s"] is None
    assert phases["preparation_complete"]["baseline_timestamp_s"] is None
    rows = difference_table(aligned)
    assert len(rows[0]) == 8
    assert "第4行" in rows[0]["参考事件与行号"]
    assert "-0.096000" in rows[0]["起止或端点差值"]
    assert "unknown" in rows[0]["起止或端点差值"]
    assert "最早可配对运动端点差异" in rows[0]["最早差异"]
