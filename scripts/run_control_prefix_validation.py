"""Repeat the bounded control prefix and compare only observed historical rules.

Reuses the previous parsed archival trace; no original-engine launch, no trace
fitting, and no historical target time is an acceptance threshold.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cogtool_py.control_models import AuxiliaryLocation, ControlConfig
from cogtool_py.generator import generate
from cogtool_py.io import implementation_fingerprint, input_hash, load_project, save_project
from cogtool_py.models import (CONTROL_ENGINE, MOTOR_ENGINE, Demonstration, DemonstrationStep, Design, Frame,
                               InitialState, ModelError, Project, Task, Widget)
from scripts.reference_validation_worker import effective_project_hashes
from scripts.run_reference_validation import protect, read, run_command, sha, stable, write

REQUIRED_PREFIX_FIELDS = ("engine_id", "engine_version", "source_commit", "initial_state_profile",
    "initial_state_provenance", "first_selected_rule", "first_firing_time_s", "first_target_rule",
    "first_target_rule_firing_time_s", "first_mouse_request_time_s", "task_stop_time_s",
    "last_device_output_time_s", "last_manual_release_time_s", "reported_task_time_s",
    "completion_status", "remaining_unsupported_mechanisms")


def variants(project, scene):
    script = generate(project, project.tasks[0])
    first = next((step for step in script.steps if step.op == "point"), None)
    if first is None:
        raise ModelError("control validation input: no generated point to target")
    auxiliary = tuple(AuxiliaryLocation(item["id"], item["frame"], item["x"], item["y"],
        json.dumps(item["source"], ensure_ascii=False, sort_keys=True)) for item in scene["auxiliary_locations"])
    configs = {
        "source_2014_defaults": ControlConfig.source_2014(
            provenance="Pinned 2014 ordinary EMMA/default initialization; scene.json source extraction; not a saved 2009 initial-state claim", auxiliary_locations=auxiliary),
        "synthetic_empty_location": ControlConfig("synthetic_controller_only", "Synthetic empty visual-location control test, no EMMA validation or 2009 initial-state inference", auxiliary_locations=auxiliary),
        "synthetic_matching_location": ControlConfig("synthetic_controller_only", "Synthetic explicitly matching visual-location control test, no EMMA validation or 2009 initial-state inference", visual_location=first.target, auxiliary_locations=auxiliary),
    }
    return {name: replace(project, engine=CONTROL_ENGINE, parameters=project.parameters.with_control_defaults(), control=config)
            for name, config in configs.items()}


def unseen_scenes(project):
    """Two explicit controller-only cases with targets/geometry unlike NP-B1."""
    parameters = project.parameters.with_control_defaults()
    result = {}
    for name, matching in (("unseen_empty_far_target", False), ("unseen_matching_other_target", True)):
        destination_geometry = (270, -20, 24, 32) if matching else (180, 60, 30, 18)
        frame = Frame("probe_frame", "Probe frame", (
            Widget("probe_left", "probe left", "", "button", 20, 10, 10, 10),
            Widget("probe_destination", "probe destination", "", "button", *destination_geometry)))
        initial = InitialState(frame.id, (-30, 5), "right", "mouse", None)
        task = Task(name, name, Demonstration(initial, (DemonstrationStep("point", target="probe_destination"),)))
        config = ControlConfig("synthetic_controller_only", "Unseen synthetic controller-only scene; no visual-completion timing injection", visual_location="probe_destination" if matching else None)
        result[name] = Project(2, name, name, CONTROL_ENGINE, parameters,
                               Design("probe_design", "Probe design", "px", (frame,), ()), (task,), control=config)
    return result


def verify_prefix(result, identity):
    issues = []
    for key in REQUIRED_PREFIX_FIELDS:
        if key not in result:
            issues.append("missing required field " + key)
    if result.get("engine_id") != CONTROL_ENGINE or result.get("engine", {}).get("name") != CONTROL_ENGINE:
        issues.append("wrong control engine identity")
    if result.get("implementation", {}).get("sha256") != identity:
        issues.append("implementation identity changed")
    if result.get("completion_status") != "partial":
        issues.append("first-request prefix not reached: " + str(result.get("completion_status")))
    for field in ("predicted_time_s", "reported_task_time_s", "task_stop_time_s", "original_rerun_s"):
        if field not in result or result[field] is not None:
            issues.append(field + " must remain explicitly null for this incomplete task")
    if not result.get("remaining_unsupported_mechanisms"):
        issues.append("missing unsupported-mechanism boundary")
    events = result.get("events", [])
    previous_stamp = None
    for index, event in enumerate(events):
        stamp = event.get("start_s")
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp < 0:
            issues.append(f"event {index}: invalid observation timestamp")
        else:
            if previous_stamp is not None and stamp < previous_stamp:
                issues.append(f"event {index}: observation timestamps go backwards")
            previous_stamp = stamp
    selected = [event for event in events if event.get("event_type") == "production_selected"]
    fired = [event for event in events if event.get("event_type") == "production_fired"]
    requests = [event for event in events if event.get("event_type") == "mouse_request"]
    if not selected or result.get("first_selected_rule") != selected[0].get("rule"):
        issues.append("first selected-rule summary disagrees with actual events")
    if not fired or result.get("first_firing_time_s") != fired[0].get("start_s"):
        issues.append("first firing summary disagrees with actual events")
    target_selected = [event for event in selected if event.get("rule") != "set-start-frame"]
    target_fired = [event for event in fired if event.get("rule") != "set-start-frame"]
    if not target_selected or result.get("first_target_rule") != target_selected[0].get("rule"):
        issues.append("first target-rule summary disagrees with actual events")
    if not target_fired or result.get("first_target_rule_firing_time_s") != target_fired[0].get("start_s"):
        issues.append("first target firing summary disagrees with actual events")
    if len(requests) != 1 or result.get("first_mouse_request_time_s") != requests[0].get("start_s"):
        issues.append("first mouse request missing, duplicate, or summary inconsistent")
    motor = result.get("motor_events", [])
    if not motor or not requests or motor[0].get("start_s") != requests[0].get("start_s"):
        issues.append("shared motor was not requested at the actual control request timestamp")
    if motor and requests and requests[0].get("event_id") not in motor[0].get("dependencies", []):
        issues.append("first motor event does not reference the control request")
    if any(event.get("state_after") is None for event in motor):
        issues.append("modeled motor events did not complete")
    for field, kinds in (("last_device_output_time_s", {"cursor_move", "click_output"}),
                         ("last_manual_release_time_s", {"cursor_finish", "click_finish"})):
        actual = [event["end_s"] for event in motor if event.get("event_type") in kinds and event.get("state_after") is not None]
        if result.get(field) != (max(actual) if actual else None):
            issues.append(field + " disagrees with motor events")
    return issues


def historical_observations(reference_analysis):
    """Use the already checked parsed point records; do not parse 355 raw lines again."""
    events = read(reference_analysis / "point_events.json")
    selected = [event for event in events if event["message"].startswith("PRODUCTION-SELECTED ")]
    fired = [event for event in events if event["message"].startswith("PRODUCTION-FIRED ")]
    first_target = next((event for event in selected if not event["message"].startswith("PRODUCTION-SELECTED SET-START-FRAME-")), None)
    target_name = first_target["message"].split(" ", 1)[1] if first_target else None
    target_fired = next((event for event in fired if event["message"] == "PRODUCTION-FIRED " + target_name), None) if target_name else None
    mouse = next((event for event in events if event["module"] == "MOTOR" and event["message"].startswith("MOVE-CURSOR OBJECT ")), None)
    return {"reference_kind": "archived_reference", "original_rerun_s": None,
            "first_selected_rule_event": selected[0] if selected else None,
            "first_fired_rule_event": fired[0] if fired else None,
            "first_target_selected_event": first_target, "first_target_fired_event": target_fired,
            "first_mouse_request_event": mouse,
            "location_writes_before_first_target": [event for event in events
                if first_target and event["line_number"] < first_target["line_number"]
                and event["module"] == "VISION"
                and event["message"].startswith("SET-BUFFER-CHUNK VISUAL-LOCATION ")],
            "cached_metadata": read(reference_analysis / "reference_metadata.json"),
            "reuse": {"parsed_point_events_path": str((reference_analysis / "point_events.json").resolve()),
                      "sha256": sha(reference_analysis / "point_events.json"), "raw_trace_reparsed": False}}


def compare_history(reference, results):
    target = reference["first_target_selected_event"]
    mouse = reference["first_mouse_request_event"]
    rows = []
    for label, result in results.items():
        selected = next((event for event in result["events"] if event["event_type"] == "production_selected" and event["rule"] != "set-start-frame"), None)
        rows.append({"profile": label, "reference_kind": "archived_reference",
            "historical_bootstrap_event": reference["first_selected_rule_event"],
            "historical_first_target_event": target,
            "historical_first_mouse_request_event": mouse,
            "historical_location_writes_before_first_target": reference["location_writes_before_first_target"],
            "python_first_selected_rule": result["first_selected_rule"],
            "python_first_target_rule": result["first_target_rule"],
            "python_first_target_selection": selected,
            "python_first_target_firing_time_s": result["first_target_rule_firing_time_s"],
            "python_first_mouse_request_time_s": result["first_mouse_request_time_s"],
            "mouse_time_difference_s": result["first_mouse_request_time_s"] - mouse["timestamp_s"] if result["first_mouse_request_time_s"] is not None and mouse else None,
            "reported_task_time_s": result["reported_task_time_s"], "completion_status": result["completion_status"],
            "agreement": "both produce a rule-driven mouse request; motor target and original task path are retained",
            "confirmed_difference": "2014 implementation applies state-dependent rule competition; synthetic configurations are explicit controller-only inputs",
            "input_unknowns": ["2009 initial visual module state", "2009 full source and runtime parameter identity"],
            "unconfirmed_cause": "the saved 2009 trace alone does not establish why FIND won after a matching location was stuffed",
            "version_scope": "selected pinned 2014 rules versus archived 2009 observations; no same-version original execution",
            "equivalence_evaluated": False, "historical_timestamp_used_as_acceptance_target": False})
    return rows


def write_history_markdown(path, reference, rows):
    def describe(event):
        return "unknown" if event is None else f"L{event['line_number']} {event['message']} @ {event['timestamp_s']} s"
    lines = ["# 历史首规则与新控制前缀", "", "读取上一轮已解析的点事件，没有重新解析原始355行。历史时间只作诊断，不作为验收目标。", "",
             "历史启动：" + describe(reference["first_selected_rule_event"]) + "。",
             "历史首目标规则：" + describe(reference["first_target_selected_event"]) + "。",
             "历史首次鼠标请求：" + describe(reference["first_mouse_request_event"]) + "。", "",
             "| 初态场景 | Python首规则 / 首目标规则 | 首目标触发(s) | 首鼠标请求(s) | Δ请求(s) | 完成状态 / 任务总时长 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        lines.append(f"| {row['profile']} | {row['python_first_selected_rule']} / {row['python_first_target_rule']} | {row['python_first_target_firing_time_s']} | {row['python_first_mouse_request_time_s']} | {row['mouse_time_difference_s']} | {row['completion_status']} / null |")
    lines.extend(["", "历史首目标规则之前的视觉位置写入证据："])
    lines.extend("- " + describe(event) for event in reference["location_writes_before_first_target"])
    lines.extend(["", "一致处：目标处理规则发出真实鼠标请求，并接入共享运动模块。不同处：2014正常初态按本轮源码规则初始化，另外两种初态是明确的合成控制层试验；它们不是对2009真实初态的候选估计。", "",
                  "已确认：选择取决于当时的视觉位置内容、模块状态及规则效用，启动规则与首目标规则分列；未实现视觉编码完成和后续脚本，任务总时间保持null。", "",
                  "仍未知：2009初始视觉状态、完整参数/源码/环境是否相同，以及其匹配位置出现后仍选择FIND的充分原因。不能仅凭历史日志认定版本差异是Python错误，也不选择最接近历史时间的场景作为真相。", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def run(input_path, scene_path, reference_analysis, out):
    input_path, scene_path, reference_analysis, out = (Path(value).resolve() for value in (input_path, scene_path, reference_analysis, out))
    if out.exists():
        raise ModelError("output exists; choose a fresh directory")
    original = load_project(input_path)
    if original.engine != "klm_baseline" or len(original.tasks) != 1:
        raise ModelError("input: expected the preserved single-task baseline project")
    scene = read(scene_path)
    models = variants(original, scene)
    unseen = unseen_scenes(original)
    reference = historical_observations(reference_analysis)
    out.mkdir(parents=True)
    protect(out)
    identity = implementation_fingerprint()
    before_state = effective_project_hashes({**models, **unseen})
    shutil.copyfile(scene_path, out / "source_scene.json")
    write(out / "reference_observations.json", reference)
    write(out / "run_manifest.json", {"started_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_path": str(input_path), "input_file_sha256": sha(input_path), "scene_path": str(scene_path),
        "scene_sha256": sha(scene_path), "implementation": identity, "source_tool_sha256": sha(Path(__file__)),
        "official_case_count": 1, "explicit_initial_state_profiles": len(models), "unseen_synthetic_cases": len(unseen),
        "independent_process_repetitions_per_profile": 3, "complete_prediction_expected": False,
        "historical_timestamp_acceptance_target": None})
    for label, project in {**models, **unseen}.items():
        save_project(project, out / "inputs" / (label + ".json"))
    commands, issues, checks, first_results, rows = [], [], {}, {}, []
    for label, project in models.items():
        model_path = out / "inputs" / (label + ".json")
        repetitions = []
        for repeat in range(1, 4):
            destination = out / "results" / label / f"repeat_{repeat}"
            command = run_command(out, f"{label}_repeat_{repeat}", [sys.executable, "-m", "cogtool_py", "predict", str(model_path), "--out", str(destination)])
            commands.append(command)
            path = destination / "result.json"
            if command["returncode"] != 0 or not path.is_file():
                issues.append(f"{label} repeat {repeat}: failed or incomplete")
                continue
            result = read(path)
            repetitions.append(result)
            issues.extend(f"{label} repeat {repeat}: {issue}" for issue in verify_prefix(result, identity["sha256"]))
            if repeat == 1:
                first_results[label] = result
        same = len(repetitions) == 3 and all(stable(result) == stable(repetitions[0]) for result in repetitions[1:])
        if not same:
            issues.append(label + ": independent-process results differ or are missing")
        saved = out / "inputs" / (label + "_roundtrip.json")
        command = run_command(out, label + "_roundtrip", [sys.executable, "-m", "cogtool_py", "roundtrip", str(model_path), "--out", str(saved)])
        commands.append(command)
        roundtrip = False
        if command["returncode"] == 0:
            destination = out / "results" / label / "roundtrip"
            command = run_command(out, label + "_roundtrip_predict", [sys.executable, "-m", "cogtool_py", "predict", str(saved), "--out", str(destination)])
            commands.append(command)
            if command["returncode"] == 0 and (destination / "result.json").is_file():
                result = read(destination / "result.json")
                roundtrip = label in first_results and stable(result) == stable(first_results[label])
                issues.extend(f"{label} roundtrip: {issue}" for issue in verify_prefix(result, identity["sha256"]))
        if not roundtrip:
            issues.append(label + ": roundtrip changed result or failed")
        destination = out / "results" / label / "same_process_A_B_A"
        command = run_command(out, label + "_same_process_A_B_A", [sys.executable, str(ROOT / "scripts/reference_validation_worker.py"), "--a", str(model_path),
            "--b", str(out / "inputs/unseen_matching_other_target.json"), "--out", str(destination)])
        commands.append(command)
        aba = read(destination / "summary.json") if (destination / "summary.json").is_file() else None
        aba_ok = command["returncode"] == 0 and aba is not None and aba.get("status") == "PASS" and aba.get("inputs_unmodified") is True
        if not aba_ok:
            issues.append(label + ": A-B-A result/state check failed")
        checks[label] = {"repeat_count": len(repetitions), "three_independent_processes_equal": same,
                         "roundtrip_equal": roundtrip, "same_process_A_B_A_pass": aba_ok, "input_sha256": input_hash(project)}
    for label in unseen:
        destination = out / "results" / label
        command = run_command(out, label, [sys.executable, "-m", "cogtool_py", "predict", str(out / "inputs" / (label + ".json")), "--out", str(destination)])
        commands.append(command)
        if command["returncode"] == 0 and (destination / "result.json").is_file():
            result = read(destination / "result.json")
            issues.extend(f"{label}: {issue}" for issue in verify_prefix(result, identity["sha256"]))
            first_results[label] = result
        else:
            issues.append(label + ": unseen synthetic prefix failed")
    comparison = compare_history(reference, {name: result for name, result in first_results.items() if name in models})
    write(out / "historical_rule_comparison.json", comparison)
    write_history_markdown(out / "HISTORICAL_RULE_COMPARISON_zh.md", reference, comparison)
    for name, result in first_results.items():
        rows.append({"case_id": original.tasks[0].id if name in models else name, "profile": name,
            "evidence_kind": "official_input_source_2014_prefix" if name == "source_2014_defaults" else "synthetic_controller_only",
            **{field: result.get(field) for field in REQUIRED_PREFIX_FIELDS}, "original_rerun_s": None,
            "artifact": f"results/{name}/repeat_1/result.json" if name in models else f"results/{name}/result.json"})
    old_rows = []
    for name in ("klm_baseline", MOTOR_ENGINE):
        path = input_path.parent / name / "result.json"
        if path.is_file():
            old = read(path)
            old_rows.append({"engine_id": old["engine"]["name"], "engine_version": old["engine"]["version"],
                             "case_id": old["task_id"], "prediction_s": old["predicted_time_s"],
                             "origin": "preserved_old_engine_result_not_recomputed_by_this_runner",
                             "source_path": str(path), "source_sha256": sha(path)})
    after_state = effective_project_hashes({**models, **unseen})
    if before_state != after_state:
        issues.append("runner-owned input objects mutated")
    if implementation_fingerprint() != identity:
        issues.append("package sources changed during this run")
    issues.extend("failed command: " + " ".join(command["command"]) for command in commands if command["returncode"] != 0)
    summary = {"status": "FAIL" if issues else "PASS_SOFTWARE_PREFIX_CHECKS_ONLY", "issues": issues,
        "completion_status": "partial", "reported_task_time_s": None, "original_rerun_s": None,
        "official_case_count": 1, "initial_state_profile_count": len(models), "unseen_synthetic_case_count": len(unseen),
        "checks": checks, "results": rows, "preserved_old_engine_results": old_rows, "commands": commands,
        "historical_cached_total_s": reference["cached_metadata"].get("cached_prediction_s"),
        "historical_timestamp_used_as_acceptance_target": False, "equivalence_evaluated": False,
        "effective_input_hashes_before": before_state, "effective_input_hashes_after": after_state,
        "implementation": identity, "finished_at_utc": datetime.now(timezone.utc).isoformat()}
    write(out / "summary.json", summary)
    write(out / "results.json", rows)
    write(out / "commands.json", commands)
    if rows:
        with (out / "results.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--scene", required=True, type=Path)
    parser.add_argument("--reference-analysis", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.input, args.scene, args.reference_analysis, args.out)
    except (ModelError, OSError, json.JSONDecodeError) as exc:
        print(f"control validation: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "issues": result["issues"], "checks": result["checks"]}, ensure_ascii=False, indent=2))
    return 1 if result["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
