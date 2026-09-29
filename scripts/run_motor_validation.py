"""Reproducible motor-subset software checks and archived NP-B1 diagnostics.

Uses a previously extracted candidate model, with explicit opt-in parameters.
No download or original-engine launch, no trace fitting, no accuracy judgement.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cogtool_py.io import implementation_fingerprint, input_hash, load_project, save_project
from cogtool_py.models import MOTOR_ENGINE, ModelError
from scripts.reference_validation_worker import effective_project_hashes
from scripts.run_reference_validation import protect, read, run_command, sha, stable, write


def synthetic_variants(project):
    """Three geometry interventions, never additional official observations."""
    variants = {}
    for name in ("farther_parent", "larger_targets", "displaced_item"):
        frames = []
        for frame in project.design.frames:
            widgets = []
            for widget in frame.widgets:
                changed = widget
                if name == "farther_parent" and widget.kind in {"context_menu", "menu_item"}:
                    changed = replace(widget, x=widget.x + 200, y=widget.y + 200)
                elif name == "larger_targets" and widget.kind in {"context_menu", "menu_item"}:
                    width, height = widget.width * 2, widget.height * 2
                    changed = replace(widget, x=widget.center[0] - math.floor(width / 2),
                                      y=widget.center[1] - math.floor(height / 2), width=width, height=height)
                elif name == "displaced_item" and widget.kind == "menu_item":
                    changed = replace(widget, x=widget.x + 80, y=widget.y + 40)
                widgets.append(changed)
            frames.append(replace(frame, widgets=tuple(widgets)))
        variants[name] = replace(project, id=project.id + "-synthetic-" + name,
                                 name="Synthetic geometry intervention: " + name,
                                 design=replace(project.design, frames=tuple(frames)))
    return variants


def verify_result(result, engine_name, identity_sha):
    issues = []
    if result.get("engine", {}).get("name") != engine_name:
        issues.append("unexpected engine identity")
    if result.get("implementation", {}).get("sha256") != identity_sha:
        issues.append("implementation identity changed during execution")
    events = result.get("events", [])
    if not events:
        issues.append("missing events")
    ids = [event.get("event_id", str(event.get("index"))) for event in events]
    if len(ids) != len(set(ids)):
        issues.append("duplicate event identifiers")
    for index, event in enumerate(events):
        values = [event.get(key) for key in ("start_s", "end_s", "duration_s")]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in values):
            issues.append(f"event {index} invalid or unknown modeled interval")
            continue
        start, end, duration = values
        if not math.isclose(end - start, duration, rel_tol=0, abs_tol=1e-9):
            issues.append(f"event {index} interval identity mismatch")
        if any(dependency not in ids[:index] for dependency in event.get("dependencies", [])):
            issues.append(f"event {index} missing/forward dependency")
        else:
            for dependency in event.get("dependencies", []):
                predecessor_end = events[ids.index(dependency)].get("end_s")
                if isinstance(predecessor_end, (int, float)) and start + 1e-9 < predecessor_end:
                    issues.append(f"event {index} starts before dependency {dependency} completes")
    total = result.get("predicted_time_s")
    if isinstance(total, bool) or not isinstance(total, (int, float)) or not math.isfinite(total):
        issues.append("missing/nonfinite predicted time")
    elif events and all(isinstance(event.get("end_s"), (int, float)) for event in events):
        if not math.isclose(total, max(event["end_s"] for event in events), rel_tol=0, abs_tol=1e-9):
            issues.append("total differs from last completion; overlapping interval durations are not summed")
    return issues


def run(input_path, reference_trace, out, reference_attributes=None):
    input_path, reference_trace, out = Path(input_path).resolve(), Path(reference_trace).resolve(), Path(out).resolve()
    if out.exists():
        raise ModelError("output already exists; choose a fresh directory")
    baseline = load_project(input_path)
    if baseline.engine != "klm_baseline":
        raise ModelError("input: require the preserved klm_baseline NP-B1 candidate")
    if baseline.id != "NP-B1-official-input-baseline" or baseline.tasks[0].id != "NP-B1":
        raise ModelError("input: expected the previously extracted NP-B1 candidate, not an arbitrary menu model")
    if len(baseline.tasks) != 1 or [step.op for step in baseline.tasks[0].demonstration.steps] != ["menu_select"]:
        raise ModelError("input: expected one NP-B1 menu_select demonstration")
    experimental = replace(baseline, engine=MOTOR_ENGINE, parameters=baseline.parameters.with_motor_defaults())
    out.mkdir(parents=True)
    identity = implementation_fingerprint()
    protect(out)
    initial_hash = effective_project_hashes({"baseline": baseline, "experimental": experimental})
    write(out / "run_manifest.json", {"started_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_path": str(input_path), "input_sha256": sha(input_path), "reference_trace": str(reference_trace),
        "reference_trace_sha256": sha(reference_trace), "implementation": identity,
        "source_tool_sha256": sha(Path(__file__)), "analyzer_sha256": sha(ROOT / "scripts/analyze_npb1_trace.py"),
        "engines": ["klm_baseline", MOTOR_ENGINE], "separate_process_repetitions_per_engine": 3,
        "official_case_count": 1, "synthetic_variant_count": 3,
        "scope": "software repeatability and archived-reference diagnostics; no official rerun or accuracy conclusion",
        "time_comparison": "endpoints; do not sum possibly overlapping experimental intervals"})
    commands, issues, rows, engine_checks = [], [], [], {}
    first_results, first_paths = {}, {}
    modelers = {"baseline": baseline, "experimental": experimental}
    for label, project in modelers.items():
        model_path = out / "inputs" / f"{label}.json"
        save_project(project, model_path)
        variants = synthetic_variants(project)
        for name, variant in variants.items():
            save_project(variant, out / "inputs" / f"{label}_{name}.json")
        repetitions = []
        for repeat in range(1, 4):
            destination = out / "results" / label / f"repeat_{repeat}"
            command = run_command(out, f"{label}_repeat_{repeat}",
                [sys.executable, "-m", "cogtool_py", "predict", str(model_path), "--out", str(destination)])
            commands.append(command)
            path = destination / "result.json"
            if command["returncode"] != 0 or not path.is_file():
                issues.append(f"{label} repeat {repeat}: prediction failed")
                continue
            result = read(path)
            issues.extend(f"{label} repeat {repeat}: {issue}" for issue in verify_result(result, project.engine, identity["sha256"]))
            repetitions.append(result)
            if repeat == 1:
                first_results[label], first_paths[label] = result, path
        repeat_equal = len(repetitions) == 3 and all(stable(item) == stable(repetitions[0]) for item in repetitions[1:])
        if not repeat_equal:
            issues.append(f"{label}: three separate-process results missing or unequal")
        roundtrip_path = out / "inputs" / f"{label}_roundtrip.json"
        command = run_command(out, f"{label}_roundtrip", [sys.executable, "-m", "cogtool_py", "roundtrip", str(model_path), "--out", str(roundtrip_path)])
        commands.append(command)
        roundtrip_equal = False
        if command["returncode"] == 0:
            destination = out / "results" / label / "roundtrip"
            command = run_command(out, f"{label}_roundtrip_predict", [sys.executable, "-m", "cogtool_py", "predict", str(roundtrip_path), "--out", str(destination)])
            commands.append(command)
            if command["returncode"] == 0 and (destination / "result.json").is_file():
                restored = read(destination / "result.json")
                roundtrip_equal = label in first_results and stable(restored) == stable(first_results[label])
                issues.extend(f"{label} roundtrip: {issue}" for issue in verify_result(restored, project.engine, identity["sha256"]))
        if not roundtrip_equal:
            issues.append(f"{label}: roundtrip result missing or unequal")
        aba_destination = out / "results" / label / "same_process_A_B_A"
        command = run_command(out, f"{label}_same_process_A_B_A", [sys.executable, str(ROOT / "scripts/reference_validation_worker.py"),
            "--a", str(model_path), "--b", str(out / "inputs" / f"{label}_farther_parent.json"), "--out", str(aba_destination)])
        commands.append(command)
        aba = read(aba_destination / "summary.json") if (aba_destination / "summary.json").is_file() else None
        aba_pass = command["returncode"] == 0 and aba is not None and aba.get("status") == "PASS" and aba.get("inputs_unmodified") is True
        if not aba_pass:
            issues.append(f"{label}: same-process A-B-A failed or incomplete")
        engine_checks[label] = {"engine": project.engine, "input_sha256": input_hash(project),
            "three_process_results_equal": repeat_equal, "roundtrip_result_equal": roundtrip_equal,
            "same_process_A_B_A_pass": aba_pass, "repeat_count": len(repetitions)}
        rows.append({"case_id": "NP-B1", "evidence_kind": "official_input_archived_reference_diagnostic",
                     "engine": project.engine, "predicted_time_s": first_results.get(label, {}).get("predicted_time_s"),
                     "repetitions": len(repetitions), "result_path": str(first_paths[label].relative_to(out)) if label in first_paths else None})
        for name in variants:
            destination = out / "results" / label / name
            command = run_command(out, f"{label}_synthetic_{name}", [sys.executable, "-m", "cogtool_py", "predict",
                str(out / "inputs" / f"{label}_{name}.json"), "--out", str(destination)])
            commands.append(command)
            path = destination / "result.json"
            result = read(path) if command["returncode"] == 0 and path.is_file() else None
            if result is None:
                issues.append(f"{label} synthetic {name}: prediction failed")
            else:
                issues.extend(f"{label} synthetic {name}: {issue}" for issue in verify_result(result, project.engine, identity["sha256"]))
            rows.append({"case_id": name, "evidence_kind": "synthetic_unit_test", "engine": project.engine,
                         "predicted_time_s": result.get("predicted_time_s") if result else None,
                         "repetitions": 1 if result else 0, "result_path": str(path.relative_to(out)) if result else None})
    analysis_path = None
    if "baseline" in first_paths:
        analysis_path = out / "trace_analysis"
        args = [sys.executable, str(ROOT / "scripts/analyze_npb1_trace.py"), "--reference-trace", str(reference_trace),
                "--baseline-result", str(first_paths["baseline"]), "--out", str(analysis_path)]
        if "experimental" in first_paths:
            args.extend(["--experimental-result", str(first_paths["experimental"])])
        if reference_attributes:
            args.extend(["--reference-attributes", str(Path(reference_attributes).resolve())])
        command = run_command(out, "analyze_archived_trace", args)
        commands.append(command)
        if command["returncode"] != 0 or not (analysis_path / "analysis.json").is_file():
            issues.append("archived trace analysis failed or incomplete")
    else:
        issues.append("no baseline output available for archived trace analysis")
    metadata_path = reference_trace.with_name("archived_reference.json")
    metadata = read(metadata_path) if metadata_path.is_file() else {}
    provenance_path = reference_trace.with_name("numerical_provenance.json")
    published = read(provenance_path).get("published_reference", {}) if provenance_path.is_file() else {}
    previous_path = input_path.parent / "python_prediction/result.json"
    previous = read(previous_path) if previous_path.is_file() else {}
    numerical = {"previous_baseline_prediction_s": previous.get("predicted_time_s"),
                 "archived_cache_prediction_s": metadata.get("cached_prediction_s"),
                 "published_prediction_s": published.get("published_prediction_s"),
                 "published_human_mean_s": published.get("human_mean_s"),
                 "current_original_prediction_s": None,
                 "current_original_status": "not_an_aligned_original_rerun",
                 "new_baseline_prediction_s": first_results.get("baseline", {}).get("predicted_time_s"),
                 "new_experimental_prediction_s": first_results.get("experimental", {}).get("predicted_time_s"),
                 "accuracy_evaluated": False, "cached_time_used_to_fit_parameters": False}
    if previous.get("predicted_time_s") is not None and "baseline" in first_results:
        preserved_fields = ("predicted_time_s", "demonstration", "steps", "events", "initial_state", "final_state", "timing_boundary")
        same_baseline = all(previous.get(field) == first_results["baseline"].get(field) for field in preserved_fields)
        engine_checks["baseline"]["preserved_prediction_semantics_unchanged"] = same_baseline
        if not same_baseline:
            issues.append("baseline semantics differ from the preserved pre-experiment result")
    for row in rows:
        row.update({"archived_cache_prediction_s": numerical["archived_cache_prediction_s"] if row["case_id"] == "NP-B1" else None,
                    "published_prediction_s": numerical["published_prediction_s"] if row["case_id"] == "NP-B1" else None,
                    "current_original_prediction_s": None})
    final_hash = effective_project_hashes(modelers)
    if final_hash != initial_hash:
        issues.append("runner-owned source Project state changed")
    if implementation_fingerprint() != identity:
        issues.append("package source identity changed during validation run")
    issues.extend(f"command failed: {record['command']}" for record in commands if record["returncode"] != 0)
    summary = {"status": "FAIL" if issues else "PASS_SOFTWARE_CHECKS_ONLY", "issues": issues,
               "official_case_count": 1, "synthetic_variant_count": 3, "engine_count": 2,
               "separate_process_repetitions_per_engine": 3, "engine_checks": engine_checks,
               "numerical_columns": numerical, "results": rows, "commands": commands,
               "effective_project_hashes_before": initial_hash, "effective_project_hashes_after": final_hash,
               "prediction_identity": identity, "time_comparison": "predicted total equals max event end, not sum of overlapping intervals",
               "trace_analysis": str(analysis_path.relative_to(out)) if analysis_path else None,
               "official_equivalence_evaluated": False, "human_accuracy_evaluated": False,
               "finished_at_utc": datetime.now(timezone.utc).isoformat()}
    write(out / "summary.json", summary)
    write(out / "results.json", rows)
    write(out / "commands.json", commands)
    with (out / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--reference-trace", required=True, type=Path)
    parser.add_argument("--reference-attributes", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.input, args.reference_trace, args.out, args.reference_attributes)
    except (ModelError, OSError, json.JSONDecodeError) as exc:
        print(f"motor validation: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "issues": result["issues"], "numerical_columns": result["numerical_columns"]}, ensure_ascii=False, indent=2))
    return 1 if result["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
