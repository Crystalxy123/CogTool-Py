"""Repeat the same experimental engine's integrated scope and preserve evidence.

No archived timestamp is a prediction input or an acceptance target. Complete
means this bounded implementation executed STOP and its required module events;
it does not mean original-engine differential or human validation succeeded.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cogtool_py.control_models import ControlConfig
from cogtool_py.io import implementation_fingerprint, input_hash, load_project, save_project
from cogtool_py.models import (CONTROL_ENGINE, Demonstration, DemonstrationStep, Design,
    Frame, InitialState, ModelError, Project, Task, Widget)
from scripts.reference_validation_worker import effective_project_hashes
from scripts.run_control_prefix_validation import variants as prefix_variants
from scripts.run_reference_validation import protect, read, run_command, sha, stable, write

MILESTONES = ("first_selected_rule", "first_target_rule", "first_firing_time_s",
    "first_mouse_request_time_s", "first_right_click_output_time_s", "menu_selection_time_s",
    "model_stop_time_s", "task_stop_time_s", "last_device_output_time_s",
    "last_manual_release_time_s", "simulation_end_time_s", "reported_task_time_s",
    "predicted_time_s", "termination_reason", "completion_status")
LEGACY_EXCLUSIONS = {"implementation", "execution_fingerprint", "program_runtime_s"}


def integrated_variants(original):
    if original.engine != CONTROL_ENGINE or original.control is None or original.control.execution_scope != "prefix_only" or len(original.tasks) != 1:
        raise ModelError("input: expected the preserved single-task control prefix project")
    scene = {"auxiliary_locations": [asdict(location) for location in original.control.auxiliary_locations]}
    variants = prefix_variants(original, scene)
    return {name: replace(project, parameters=project.parameters.with_vision_defaults(),
        control=replace(project.control, execution_scope="integrated_task",
            auxiliary_locations=original.control.auxiliary_locations,
            provenance=("Pinned 2014 normal source initialization" if name == "source_2014_defaults" else
                        "Explicit synthetic initial buffer configuration, not a claim about 2009 state") +
                        "; actual shared VisionModule events, no prescribed completion updates"))
        for name, project in variants.items()}


def synthetic_variants(original):
    """A small new target with same/different fixation, plus a local factor probe."""
    widget = Widget("probe_target", "new target", "new target", "button", 60, 25, 40, 30)
    task = Task("new_visual_scene", "New visual scene", Demonstration(
        InitialState("probe_frame", (0, 0), "right", "mouse", None),
        (DemonstrationStep("point", target=widget.id),)))
    result = {}
    for name, eye in (("synthetic_same_eye", (80, 40)), ("synthetic_different_eye", (0, 0))):
        config = ControlConfig("synthetic_controller_only",
            "Independent synthetic fixation input; actual EMMA events and unchanged effective parameters",
            visual_location=widget.id, execution_scope="integrated_task", initial_eye=eye)
        result[name] = Project(2, name, name, CONTROL_ENGINE, original.parameters.with_vision_defaults(),
            Design("probe_design", "Probe", "px", (Frame("probe_frame", "Probe", (widget,)),), ()), (task,), config)
    base = result["synthetic_different_eye"]
    result["synthetic_encoding_factor_1p5"] = replace(base, id="synthetic_encoding_factor_1p5",
        name="Synthetic local encoding-factor probe", control=replace(base.control,
            provenance="Independent synthetic fixation and encoding-factor input; actual EMMA events, no prescribed completion"),
        parameters=base.parameters.override(
            "visual_encoding_factor_s", base.parameters.value("visual_encoding_factor_s") * 1.5,
            source="Explicit synthetic local sensitivity probe: encoding factor multiplied by1.5; no claim that concurrent task total is monotone"))
    return result


def finite_time(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def verify_complete(result, implementation_sha256, expected_input_sha256=None):
    """Check evidence relationships, not expected task totals or fitted traces."""
    issues = []
    issues.extend("missing milestone field " + key for key in MILESTONES if key not in result)
    if result.get("engine_id") != CONTROL_ENGINE or result.get("engine", {}).get("name") != CONTROL_ENGINE:
        issues.append("wrong experimental engine identity")
    if result.get("execution_scope") != "integrated_task":
        issues.append("wrong execution scope")
    if not result.get("engine_version") or result["engine_version"] != result.get("engine", {}).get("version"):
        issues.append("engine version summary disagrees with identity")
    if result.get("implementation", {}).get("sha256") != implementation_sha256:
        issues.append("implementation identity differs from frozen run")
    if expected_input_sha256 is not None and result.get("input_sha256") != expected_input_sha256:
        issues.append("effective input identity differs from saved model")
    if result.get("completion_status") != "complete":
        issues.append("bounded task did not complete: " + str(result.get("completion_status")))
    if "original_rerun_s" not in result or result["original_rerun_s"] is not None:
        issues.append("original rerun must remain explicitly null")
    if result.get("remaining_unsupported_mechanisms") != [] or result.get("blocker") is not None:
        issues.append("completion retains a blocker or missing unsupported-path evidence")
    if result.get("control_configuration", {}).get("updates") != []:
        issues.append("integrated input includes prescribed completion updates or omits their evidence")
    total = result.get("reported_task_time_s")
    if not finite_time(total) or result.get("predicted_time_s") != total or result.get("simulation_end_time_s") != total:
        issues.append("complete total must equal finite simulated end, not STOP or a wall-clock value")
    control, motor, vision = (result.get(key, []) for key in ("events", "motor_events", "vision_events"))
    stops = [e for e in control if e.get("event_type") == "production_fired" and e.get("rule") == "stop"]
    stop_records = [e for e in control if e.get("event_type") == "model_stop"]
    if len(stops) != 1 or len(stop_records) != 1:
        issues.append("complete result requires one actual STOP firing and model_stop record")
    elif result.get("model_stop_time_s") != stops[0].get("start_s") or result.get("task_stop_time_s") != stops[0].get("start_s") or stop_records[0].get("start_s") != stops[0].get("start_s"):
        issues.append("STOP summaries disagree with actual firing")
    boundary = [e for e in control if e.get("event_type") == "task_boundary"]
    if (len(boundary) != 1 or boundary[0].get("details", {}).get("full_task_completed") is not True or
            boundary[0].get("details", {}).get("pending_events") != 0):
        issues.append("complete result lacks exhausted-queue task boundary evidence")
    if result.get("termination_reason") != "event_queue_exhausted_after_stop":
        issues.append("termination reason is not the implemented source run boundary")
    if any(e.get("state_after") is None for e in motor):
        issues.append("incomplete motor events cannot count as completed output")
    if not vision or any(e.get("status") != "executed" or e.get("state_after") is None for e in vision):
        issues.append("pending/cancelled/unexecuted visual events cannot masquerade as completion")
    requests = [e for e in vision if e.get("event_type") == "visual_attention_request"]
    encodings = [e for e in vision if e.get("event_type") == "visual_encoding_complete" and e.get("status") == "executed"]
    ids = [e.get("request_id") for e in requests]
    if not ids or None in ids or len(ids) != len(set(ids)):
        issues.append("missing or duplicate visual request identities")
    for request in requests:
        completions = [e for e in encodings if e.get("request_id") == request.get("request_id")]
        if len(completions) != 1 or completions[0].get("target") != request.get("target"):
            issues.append("visual request lacks exactly one matching encoding completion: " + str(request.get("request_id")))
    if any(e.get("request_id") not in ids for e in encodings):
        issues.append("orphan visual encoding completion")
    actual_times = []
    for label, events in (("control", control), ("motor", motor), ("vision", vision)):
        for event in events:
            for key in ("start_s", "end_s"):
                if not finite_time(event.get(key)):
                    issues.append(label + " event has invalid " + key)
            if finite_time(event.get("start_s")) and finite_time(event.get("end_s")) and event["end_s"] < event["start_s"]:
                issues.append(label + " event ends before it starts")
        if label != "control":
            actual_times.extend(e["end_s"] for e in events if finite_time(e.get("end_s")) and
                                (e.get("status") == "executed" if label == "vision" else e.get("state_after") is not None))
    actual_times.extend(e["start_s"] for e in stops if finite_time(e.get("start_s")))
    if not actual_times or result.get("simulation_end_time_s") != max(actual_times):
        issues.append("simulation end differs from last actually executed module/STOP event")
    for field, kinds in (("last_device_output_time_s", {"cursor_move", "click_output"}),
                         ("last_manual_release_time_s", {"cursor_finish", "click_finish"})):
        times = [e["end_s"] for e in motor if e.get("event_type") in kinds and e.get("state_after") is not None and finite_time(e.get("end_s"))]
        if result.get(field) != (max(times) if times else None):
            issues.append(field + " differs from completed motor events")
    outputs = [e for e in motor if e.get("event_type") in {"cursor_move", "cursor_noop", "click_output"} and e.get("state_after") is not None]
    expected = Counter((s["index"], s["op"], s.get("target")) for s in result.get("steps", []) if s.get("op") in {"point", "click", "right_click"})
    actual = Counter((e.get("step_index"), e.get("op"), e.get("target")) for e in outputs)
    if not expected or actual != expected:
        issues.append("generated device steps and actually completed outputs differ")
    right = [e for e in outputs if e.get("op") == "right_click"]
    selections = [e for e in control if e.get("event_type") == "menu_selection"]
    if result.get("first_right_click_output_time_s") != (right[0]["end_s"] if right else None):
        issues.append("first right-click milestone differs from actual device output")
    if result.get("menu_selection_time_s") != (selections[-1]["start_s"] if selections else None):
        issues.append("menu selection milestone differs from actual state change")
    if len([e for e in control if e.get("event_type") == "menu_open"]) != len(right):
        issues.append("right-click output and menu-open counts differ")
    if len([e for e in control if e.get("event_type") == "production_fired" and e.get("rule") == "think"]) != len([s for s in result.get("steps", []) if s.get("op") == "think"]):
        issues.append("generated Think and fired Think counts differ")
    final = result.get("final_state", {})
    if final.get("goal_state") != "stop" or final.get("manual_state") != "free":
        issues.append("final goal/manual state is not stopped/free")
    for field in ("visual_preparation", "visual_processor", "visual_execution"):
        if final.get("vision", {}).get(field) != "free":
            issues.append("final visual resource is not free: " + field)
    if final.get("vision", {}).get("pending_events") != [] or final.get("vision", {}).get("unsupported_reason") is not None:
        issues.append("final visual state retains pending events or unsupported reason")
    return issues


def legacy_comparison(before, after):
    clean = lambda value: {key: item for key, item in value.items() if key not in LEGACY_EXCLUSIONS}
    differences = []
    def walk(a, b, path=""):
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                if key not in a or key not in b:
                    differences.append(path + "." + key)
                else:
                    walk(a[key], b[key], path + "." + key)
        elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for index, (left, right) in enumerate(zip(a, b)):
                walk(left, right, path + f"[{index}]")
        elif a != b:
            differences.append(path)
    walk(clean(before), clean(after))
    return {"equal": not differences, "changed_fields": differences,
            "excluded_fields": sorted(LEGACY_EXCLUSIONS),
            "input_hash_unchanged": before.get("input_sha256") == after.get("input_sha256"),
            "engine_identity_unchanged": before.get("engine") == after.get("engine"),
            "baseline_prediction_s": before.get("predicted_time_s"), "current_prediction_s": after.get("predicted_time_s")}


def local_encoding_observation(result):
    requests = [e for e in result["vision_events"] if e["event_type"] == "visual_attention_request"]
    return {"input_sha256": result["input_sha256"], "reported_task_time_s": result["reported_task_time_s"],
        "initial_eye": result["control_configuration"].get("initial_eye"),
        "encoding_factor_s": result["parameters"]["visual_encoding_factor_s"]["value"],
        "request_observations": [{"request_id": e["request_id"], "target": e["target"],
            "requested_at_s": e["start_s"], "raw_encoding_s": e["details"]["raw_encoding_s"],
            "eccentricity_deg": e["details"]["eccentricity_deg"],
            "encoding_completion_s": [v["end_s"] for v in result["vision_events"] if
                v["event_type"] == "visual_encoding_complete" and v["request_id"] == e["request_id"] and v["status"] == "executed"]}
            for e in requests],
        "scope": "synthetic local encoding observations; no task-total monotonicity assertion"}


def visual_milestones(result):
    free = lambda state: all(state.get(key) == "free" for key in
        ("visual_preparation", "visual_processor", "visual_execution"))
    releases = [change["time_s"] for change in result.get("vision_state_changes", [])
                if free(change.get("after", {})) and not free(change.get("before", {}))]
    executed = [event for event in result.get("vision_events", []) if event.get("status") == "executed"]
    return {"last_visual_resource_release_time_s": max(releases) if releases else None,
            "last_visual_event_time_s": max((event["end_s"] for event in executed), default=None),
            "visual_request_count": sum(event["event_type"] == "visual_attention_request" for event in executed),
            "encoding_completion_count": sum(event["event_type"] == "visual_encoding_complete" for event in executed)}


def run(input_path, out):
    input_path, out = Path(input_path).resolve(), Path(out).resolve()
    if out.exists():
        raise ModelError("output exists; choose a fresh directory")
    original = load_project(input_path)
    models, synthetics = integrated_variants(original), synthetic_variants(original)
    all_models = {**models, **synthetics}
    baseline = input_path.parent
    for name in ("klm_baseline", "motor", "control_prefix"):
        if not (baseline / (name + ".json")).is_file() or not (baseline / name / "result.json").is_file():
            raise ModelError("missing preserved baseline for " + name)
    out.mkdir(parents=True)
    protect(out)
    identity = implementation_fingerprint()
    before = effective_project_hashes(all_models)
    write(out / "manifest.json", {"started_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_input": str(input_path), "source_input_sha256": sha(input_path), "implementation": identity,
        "runner_sha256": sha(Path(__file__)), "official_case_count": 1, "initial_state_profile_count": 3,
        "independent_process_repetitions_per_profile": 3, "synthetic_scene_count": 2, "parameter_derived_case_count": 1,
        "original_rerun_s": None, "reference_totals_used_as_acceptance_targets": False})
    for name, project in all_models.items():
        save_project(project, out / "inputs" / (name + ".json"))
    commands, issues, checks, results = [], [], {}, {}
    def command(label, args):
        record = run_command(out, label, [sys.executable, *map(str, args)])
        commands.append(record)
        if record["returncode"]:
            issues.append(label + ": subprocess failed")
        return record
    def predict(name, path, destination, label):
        record = command(label, ["-m", "cogtool_py", "predict", path, "--out", destination])
        result_path = destination / "result.json"
        if record["returncode"] or not result_path.is_file():
            issues.append(label + ": result missing or process failed")
            return None
        result = read(result_path)
        issues.extend(label + ": " + issue for issue in verify_complete(result, identity["sha256"], input_hash(all_models[name])))
        return result
    for name in models:
        path = out / "inputs" / (name + ".json")
        repeated = []
        for repetition in range(1, 4):
            result = predict(name, path, out / "results" / name / f"repeat_{repetition}", name + f"_repeat_{repetition}")
            if result is not None:
                repeated.append(result)
                if repetition == 1:
                    results[name] = result
        same = len(repeated) == 3 and all(stable(r) == stable(repeated[0]) for r in repeated[1:])
        saved = out / "inputs" / (name + "_roundtrip.json")
        roundtrip = False
        if command(name + "_roundtrip", ["-m", "cogtool_py", "roundtrip", path, "--out", saved])["returncode"] == 0:
            result = predict(name, saved, out / "results" / name / "roundtrip", name + "_roundtrip_predict")
            roundtrip = result is not None and name in results and stable(result) == stable(results[name])
        aba_dir = out / "results" / name / "same_process_A_B_A"
        aba_command = command(name + "_same_process_A_B_A", [ROOT / "scripts/reference_validation_worker.py", "--a", path,
            "--b", out / "inputs/synthetic_different_eye.json", "--out", aba_dir])
        aba = read(aba_dir / "summary.json") if (aba_dir / "summary.json").is_file() else {}
        aba_ok = aba_command["returncode"] == 0 and aba.get("status") == "PASS" and aba.get("inputs_unmodified") is True
        checks[name] = {"actual_repetitions": len(repeated), "three_independent_processes_equal": same,
                       "roundtrip_equal": roundtrip, "same_process_A_B_A_pass": aba_ok, "input_sha256": input_hash(models[name])}
        if not all((same, roundtrip, aba_ok)):
            issues.append(name + ": repeat/roundtrip/A-B-A check failed")
    for name in synthetics:
        result = predict(name, out / "inputs" / (name + ".json"), out / "results" / name, name)
        if result is not None:
            results[name] = result
    legacy = {}
    for name in ("klm_baseline", "motor", "control_prefix"):
        dest = out / "legacy" / name
        record = command("legacy_" + name, ["-m", "cogtool_py", "predict", baseline / (name + ".json"), "--out", dest])
        if record["returncode"] or not (dest / "result.json").is_file():
            issues.append("legacy " + name + ": result missing or subprocess failed")
            continue
        old, new = read(baseline / name / "result.json"), read(dest / "result.json")
        comparison = legacy_comparison(old, new)
        comparison.update(baseline_result_sha256=sha(baseline / name / "result.json"), current_result_sha256=sha(dest / "result.json"),
                          baseline_path=str(baseline / name / "result.json"), current_path=str(dest / "result.json"))
        legacy[name] = comparison
        if not comparison["equal"]:
            issues.append("legacy " + name + ": full result regression")
    local = {name: local_encoding_observation(results[name]) for name in synthetics if name in results}
    write(out / "local_encoding_observations.json", local)
    rows = [{"case_id": result["task_id"], "profile": name,
        "evidence_kind": "official_input_source_2014_integrated_diagnostic" if name == "source_2014_defaults" else "synthetic_initial_state_or_parameter_probe",
        "engine_id": result["engine_id"], "engine_version": result["engine_version"],
        **{key: result.get(key) for key in MILESTONES}, **visual_milestones(result), "input_sha256": result["input_sha256"],
        "execution_fingerprint": result["execution_fingerprint"], "original_rerun_s": None,
        "artifact": f"results/{name}/repeat_1/result.json" if name in models else f"results/{name}/result.json"}
        for name, result in results.items()]
    after = effective_project_hashes(all_models)
    if before != after:
        issues.append("effective runner input objects mutated")
    if implementation_fingerprint() != identity:
        issues.append("package sources changed during run")
    summary = {"status": "FAIL" if issues else "PASS_BOUNDED_SOFTWARE_EXECUTION_CHECKS_ONLY", "issues": issues,
        "official_case_count": 1, "initial_state_profile_count": 3, "synthetic_scene_count": 2, "parameter_derived_case_count": 1,
        "checks": checks, "results": rows, "legacy_regressions": legacy, "commands": commands,
        "original_rerun_s": None, "equivalence_or_accuracy_evaluated": False,
        "reference_totals_used_as_acceptance_targets": False, "task_total_monotonicity_asserted": False,
        "effective_input_hashes_before": before, "effective_input_hashes_after": after,
        "implementation": identity, "finished_at_utc": datetime.now(timezone.utc).isoformat()}
    write(out / "summary.json", summary)
    write(out / "commands.json", commands)
    write(out / "results.json", rows)
    write(out / "legacy_regressions.json", legacy)
    if rows:
        with (out / "results.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        summary = run(args.input, args.out)
    except (ModelError, OSError, json.JSONDecodeError) as exc:
        print(f"visual validation: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": summary["status"], "issues": summary["issues"], "checks": summary["checks"]}, ensure_ascii=False, indent=2))
    return 1 if summary["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
