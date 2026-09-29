"""Execute the preregistered diagnostics without modifying the frozen engine.

Identity/provenance checks compare normalized complete calculation records.
Geometry/fixation cases are retained regardless of outcome, and impose no
task-total monotonicity condition or agreement with a reference prediction.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cogtool_py.engine import predict
from cogtool_py.io import export_result, implementation_fingerprint, input_hash, load_project, save_project
from cogtool_py.models import ModelError, Project
from scripts.reference_validation_worker import effective_project_hashes


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def differences(left, right, path=""):
    if isinstance(left, dict) and isinstance(right, dict):
        result = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                result.append({"path": path + "." + key, "left": left.get(key), "right": right.get(key),
                               "missing_side": "left" if key not in left else "right"})
            else:
                result.extend(differences(left[key], right[key], path + "." + key))
        return result
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [item for i, (a, b) in enumerate(zip(left, right)) for item in differences(a, b, path + f"[{i}]")]
    return [] if left == right else [{"path": path, "left": left, "right": right}]


NORMALIZATION_POLICY = {
    "excluded_top_level_fields": ["program_runtime_s", "input_sha256", "execution_fingerprint"],
    "kept": "all other result fields including formulas, parameters, rule decisions, timings, resources, termination, implementation identity and version",
    "identity": "inverse deterministic input-ID bijection, including derived location chunk strings and serialized auxiliary source IDs",
    "provenance": "restore only the exact artificial reference-provenance strings introduced by this test; no general removal of source fields",
    "set_presentation": "sort scene_locations after inverse renaming because this field is an ID-sorted presentation of a runtime set; all other sequence order retained",
    "json_provenance": "canonicalize valid JSON object/array strings after recursively applying identity inverse",
    "numeric": "exact comparisons; no rounding, shift, time tolerance or total-time fitting",
}


def normalize_result(result, inverse=None, string_restore=None):
    inverse, string_restore = inverse or {}, string_restore or {}
    token = re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(re.escape(x) for x in sorted(inverse, key=len, reverse=True)) + r")(?![A-Za-z0-9_-])") if inverse else None
    def normalize(value, key=None):
        if isinstance(value, dict):
            return {name: normalize(item, name) for name, item in value.items()}
        if isinstance(value, list):
            items = [normalize(item) for item in value]
            return sorted(items) if key == "scene_locations" else items
        if isinstance(value, str):
            if value in string_restore:
                return string_restore[value]
            if value.startswith(("{", "[")):
                try:
                    encoded = json.loads(value)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(encoded, (dict, list)):
                        return json.dumps(normalize(encoded), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            return token.sub(lambda match: inverse[match.group(0)], value) if token else value
        return value
    return normalize({key: value for key, value in result.items()
                      if key not in NORMALIZATION_POLICY["excluded_top_level_fields"]})


def rename_identity(model):
    result = deepcopy(model)
    mapping = {model["id"]: "renamed-project", model["design"]["id"]: "renamed-design"}
    source_mapping = {}
    def assign(old, new):
        if old in mapping:
            raise ModelError("diagnostic identity definitions are not globally unique: " + old)
        mapping[old] = new
        match = re.fullmatch(r"[fwgt](\d+)", old)
        if match:
            source_mapping[match.group(1)] = "source-" + new
    for index, frame in enumerate(model["design"]["frames"], 1):
        assign(frame["id"], f"id-frame-{index:03}")
    index = 0
    for frame in model["design"]["frames"]:
        for widget in frame["widgets"]:
            index += 1
            assign(widget["id"], f"id-widget-{index:03}")
    for index, transition in enumerate(model["design"]["transitions"], 1):
        assign(transition["id"], f"id-transition-{index:03}")
    for index, task in enumerate(model["tasks"], 1):
        assign(task["id"], "renamed-case" if index == 1 else f"renamed-case-{index}")
    for index, auxiliary in enumerate(model["control"]["auxiliary_locations"], 1):
        assign(auxiliary["id"], f"id-group-{index:03}")
    reference_fields = {"id", "frame", "parent", "from_frame", "to_frame", "target", "focus", "transition",
                        "visual_location", "visual_content", "visible_targets"}
    def update(value, field=None):
        if isinstance(value, dict):
            return {key: update(item, key) for key, item in value.items()}
        if isinstance(value, list):
            return [update(item, field) for item in value]
        if isinstance(value, str) and field in reference_fields:
            return mapping.get(value, value)
        return value
    result = update(result)
    for auxiliary in result["control"]["auxiliary_locations"]:
        metadata = json.loads(auxiliary["source"])
        metadata["object_id"] = source_mapping[metadata["object_id"]]
        metadata["members"] = [source_mapping[member] for member in metadata["members"]]
        auxiliary["source"] = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    for original_frame, renamed_frame in zip(model["design"]["frames"], result["design"]["frames"]):
        assert original_frame["name"] == renamed_frame["name"]
        for original_widget, renamed_widget in zip(original_frame["widgets"], renamed_frame["widgets"]):
            assert all(original_widget[key] == renamed_widget[key] for key in ("name", "label", "kind", "x", "y", "width", "height"))
    return result, mapping, source_mapping


def rebuild_groups(model):
    records = []
    frames = {frame["id"]: frame for frame in model["design"]["frames"]}
    for auxiliary in model["control"]["auxiliary_locations"]:
        metadata = json.loads(auxiliary["source"])
        if metadata.get("class") != "SimpleWidgetGroup":
            raise ModelError("diagnostic group must retain explicit SimpleWidgetGroup definitions")
        widgets = {widget["id"]: widget for widget in frames[auxiliary["frame"]]["widgets"]}
        member_ids = ["w" + value for value in metadata["members"]]
        if not member_ids or any(value not in widgets for value in member_ids):
            raise ModelError("diagnostic source group members do not resolve to preserved definitions")
        members = [widgets[value] for value in member_ids]
        left, top = min(w["x"] for w in members), min(w["y"] for w in members)
        right = max(w["x"] + w["width"] for w in members)
        bottom = max(w["y"] + w["height"] for w in members)
        bounds = {"x": left, "y": top, "width": right - left, "height": bottom - top}
        before = {"x": auxiliary["x"], "y": auxiliary["y"], "bounds": metadata["bounds"]}
        auxiliary["x"], auxiliary["y"] = left + math.floor((right-left)/2), top + math.floor((bottom-top)/2)
        metadata["bounds"] = bounds
        auxiliary["source"] = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        records.append({"group": auxiliary["id"], "member_ids": member_ids, "before": before,
                        "after": {"x": auxiliary["x"], "y": auxiliary["y"], "bounds": bounds}})
    return records


def build_cases(original, plan):
    if [item["id"] for item in plan["diagnostic_plan"]["synthetic_cases"]] != ["target_x_plus_30", "target_width_times_1p5", "initial_eye_target"]:
        raise ModelError("unsupported diagnostic plan; this script only implements the registered three transformations")
    base = original.to_dict()
    cases = {"baseline": {"model": base, "claim": "frozen baseline recomputation"}}
    renamed, identity_map, source_map = rename_identity(base)
    cases["identity_rename"] = {"model": renamed, "identity_map": identity_map, "source_id_map": source_map,
        "inverse": {new: old for old, new in {**identity_map, **source_map}.items()},
        "claim": "same computation after inverse identity normalization"}
    original_provenance = base["control"]["provenance"]
    notes = {
        "reference_with_tokens": "diagnostic reference published=1117.875; cached=2218.25; trace=/synthetic/reference/3049/trace.txt",
        "reference_replaced": "diagnostic reference published=99001.5; cached=-12345.25; trace=/unrelated/0001/other.txt",
    }
    for name, note in notes.items():
        model = deepcopy(base)
        model["control"]["provenance"] = original_provenance + "; " + note
        cases[name] = {"model": model, "string_restore": {model["control"]["provenance"]: original_provenance},
            "reference_payload": {"reference_note": note, "classification": "artificial sentinel metadata; not actual reference results"},
            "claim": "reference numeric/path tokens in provenance cannot affect normalized computation"}
    cases["reference_removed"] = {"model": deepcopy(base),
        "claim": "remove artificial external reference payload and reference provenance notes before prediction"}
    menu_steps = [step for task in base["tasks"] for step in task["demonstration"]["steps"] if step["op"] == "menu_select"]
    if len(menu_steps) != 1:
        raise ModelError("registered diagnostic input requires one selected menu item")
    selected = menu_steps[0]["target"]
    for label in ("target_x_plus_30", "target_width_times_1p5"):
        model = deepcopy(base)
        targets = [widget for frame in model["design"]["frames"] for widget in frame["widgets"] if widget["id"] == selected]
        if len(targets) != 1 or targets[0]["kind"] != "menu_item":
            raise ModelError("registered selected target must resolve to one menu_item")
        previous = deepcopy(targets[0])
        if label == "target_x_plus_30":
            targets[0]["x"] += 30
        else:
            targets[0]["width"] *= 1.5
        cases[label] = {"model": model, "changed_widget_before": previous, "changed_widget_after": deepcopy(targets[0]),
            "derived_groups": rebuild_groups(model), "claim": "synthetic rule response and repeatability only; no total-time monotonicity assertion"}
    widgets = {widget["id"]: widget for frame in base["design"]["frames"] for widget in frame["widgets"]}
    first = widgets[widgets[selected]["parent"]]
    first_center = [first["x"] + math.floor(first["width"]/2), first["y"] + math.floor(first["height"]/2)]
    for label, eye in (("initial_eye_zero_control", [0, 0]), ("initial_eye_target", first_center)):
        model = deepcopy(base)
        model["control"].update(profile="synthetic_controller_only", auto_stuffing=False,
            visual_location=first["id"], location_requested=False, visual_content=None, initial_eye=eye,
            provenance="Preregistered synthetic post-start matching location and prescribed fixation; actual vision events, not a 2009 state claim")
        cases[label] = {"model": model, "claim": "local encoding relationship versus same synthetic profile; no task-total monotonicity claim"}
    return cases


def self_checks():
    sample = {"time_s": .123, "state": {"target": "id-widget-001", "scene_locations": ["id-widget-002", "id-widget-001"]},
              "source": '{"object_id":"source-id-widget-001"}', "implementation": {"sha256": "frozen"}}
    inverse = {"id-widget-001": "w8", "id-widget-002": "w14", "source-id-widget-001": "8"}
    normalized = normalize_result(sample, inverse)
    assert normalized["state"] == {"target": "w8", "scene_locations": ["w14", "w8"]}
    assert normalized["source"] == '{"object_id":"8"}'
    assert differences(normalized, {**normalized, "time_s": .124})
    assert differences(normalized, {**normalized, "implementation": {"sha256": "changed"}})
    return {"status": "pass", "scope": "synthetic helper checks; identity normalization preserves numerical and implementation differences"}


def reference_answer_fields(value, path=""):
    known = {"published_prediction_s", "cached_prediction_s", "archived_prediction_s", "reference_total_s", "trace_times"}
    if isinstance(value, dict):
        return [item for key, child in value.items() for item in
                ([path + "." + key] if key in known else reference_answer_fields(child, path + "." + key))]
    if isinstance(value, list):
        return [item for index, child in enumerate(value) for item in reference_answer_fields(child, path + f"[{index}]")]
    return []


def run(input_path, plan_path, out):
    input_path, plan_path, out = map(lambda value: Path(value).resolve(), (input_path, plan_path, out))
    if out.exists():
        raise ModelError("diagnostic output already exists; refusing overwrite")
    plan = read(plan_path)
    frozen = plan["frozen_implementation"]
    if implementation_fingerprint() != frozen:
        raise ModelError("package identity is not the preregistered frozen implementation")
    input_before, plan_before = file_sha(input_path), file_sha(plan_path)
    original = load_project(input_path)
    cases = build_cases(original, plan)
    projects = {label: Project.from_dict(case["model"]) for label, case in cases.items()}
    initial_states = effective_project_hashes(projects)
    out.mkdir(parents=True)
    write(out / "helper_checks.json", self_checks())
    write(out / "normalization_policy.json", NORMALIZATION_POLICY)
    write(out / "preregistration.json", {"plan_path": str(plan_path), "plan_sha256": plan_before,
        "diagnostic_plan": plan["diagnostic_plan"], "frozen_implementation": frozen,
        "normalization_written_before_prediction": True, "all_cases_registered_before_prediction": list(cases),
        "synthetic_plan_count": 3, "fixation_control_is_paired_comparator_not_fourth_selected_case": True,
        "original_rerun_s": None, "comparison_to_reference_accuracy": "not_evaluated"})
    for label, case in cases.items():
        case_dir = out / label
        save_project(projects[label], case_dir / "input.json")
        write(case_dir / "test_envelope.json", {"prediction_input": case["model"],
            **({"reference_payload": case["reference_payload"]} if "reference_payload" in case else {})})
        write(case_dir / "transformation.json", {key: value for key, value in case.items() if key not in {"model", "reference_payload"}})
    summaries, normalized, issues = {}, {}, []
    for label, case in cases.items():
        project, records, results = projects[label], [], []
        for repeat in (1, 2):
            before = effective_project_hashes(projects)
            output_dir = out / label / f"repeat_{repeat}"
            try:
                result = predict(project)
            except ModelError as exc:
                write(output_dir / "error.json", {"execution_status": "error", "error": str(exc), "traceback": traceback.format_exc()})
                records.append({"repeat": repeat, "execution_status": "error", "error": str(exc)})
                issues.append(label + ": prediction error")
                continue
            data = result.to_dict()
            export_result(result, output_dir)
            results.append(data)
            after = effective_project_hashes(projects)
            package = implementation_fingerprint()
            record = {"repeat": repeat, "execution_status": data["completion_status"],
                "reported_task_time_s": data["reported_task_time_s"], "input_sha256": input_hash(project),
                "result_file_sha256": file_sha(output_dir / "result.json"),
                "all_effective_inputs_before": before, "all_effective_inputs_after": after,
                "inputs_unmodified": before == after == initial_states,
                "implementation_sha256": package["sha256"], "implementation_matches_frozen": package == frozen}
            records.append(record)
            if not record["inputs_unmodified"] or package != frozen:
                issues.append(label + ": frozen state or implementation changed")
        repeated = len(results) == 2 and {k: v for k, v in results[0].items() if k != "program_runtime_s"} == {k: v for k, v in results[1].items() if k != "program_runtime_s"}
        if not repeated:
            issues.append(label + ": repeated deterministic results differ or are missing")
        if results:
            normalized[label] = normalize_result(results[0], case.get("inverse"), case.get("string_restore"))
            write(out / label / "normalized_computation.json", normalized[label])
        summary = {"evidence_kind": "synthetic_metamorphic_diagnostic", "claim": case["claim"],
            "execution_status": results[0]["completion_status"] if results else "error",
            "repeat_equal": repeated, "input_sha256": input_hash(project),
            "content_hash_changed_from_baseline": input_hash(project) != input_hash(original),
            "claim_of_reference_agreement": False, "total_time_monotonicity_asserted": False, "runs": records}
        summaries[label] = summary
        write(out / label / "summary.json", summary)
    invariants = {}
    for label in ("identity_rename", "reference_with_tokens", "reference_removed", "reference_replaced"):
        if label not in normalized or "baseline" not in normalized:
            invariants[label] = {"comparison_status": "not_run", "equal": None}
            continue
        changes = differences(normalized["baseline"], normalized[label])
        write(out / label / "computation_differences.json", changes)
        invariants[label] = {"comparison_status": "pass" if not changes else "mismatch", "equal": not changes,
                             "difference_count": len(changes), "normalized_sha256": digest(normalized[label])}
        if changes:
            issues.append(label + ": normalized computation changed")
    synthetic_observations = {}
    for label in ("target_x_plus_30", "target_width_times_1p5", "initial_eye_zero_control", "initial_eye_target"):
        if label not in normalized:
            continue
        data = read(out / label / "repeat_1/result.json")
        synthetic_observations[label] = {"execution_status": data["completion_status"],
            "reported_task_time_s": data["reported_task_time_s"], "termination_reason": data["termination_reason"],
            "local_encoding": [{"target": event["target"], "requested_at_s": event["start_s"],
                "eccentricity_deg": event["details"]["eccentricity_deg"], "raw_encoding_s": event["details"]["raw_encoding_s"]}
                for event in data["vision_events"] if event["event_type"] == "visual_attention_request"],
            "fired_rules": [{"rule": event["rule"], "time_s": event["start_s"]} for event in data["events"] if event["event_type"] == "production_fired"],
            "no_reference_agreement_or_total_monotonicity_assertion": True}
    final_package = implementation_fingerprint()
    preserved = file_sha(input_path) == input_before and file_sha(plan_path) == plan_before and final_package == frozen
    if not preserved:
        issues.append("frozen input, plan or package changed")
    summary = {"status": "pass" if not issues else "mismatch", "issues": issues,
        "invariant_checks": invariants, "cases": summaries, "synthetic_observations": synthetic_observations,
        "synthetic_plan_count": 3, "all_cases_retained": True, "outcome_based_selection": False,
        "frozen_implementation_before": frozen, "frozen_implementation_after": final_package,
        "input_file_sha256_before": input_before, "input_file_sha256_after": file_sha(input_path),
        "plan_sha256_before": plan_before, "plan_sha256_after": file_sha(plan_path),
        "frozen_materials_preserved": preserved, "script_sha256": file_sha(Path(__file__)),
        "baseline_reference_answer_field_paths": reference_answer_fields(original.to_dict()),
        "baseline_contains_reference_answer_fields": bool(reference_answer_fields(original.to_dict())),
        "reference_isolation_scope": "Artificial external reference payload excluded from Project construction; numeric/path provenance sentinels changed then exactly restored only for output comparison; no actual reference answer loaded",
        "original_rerun_s": None, "reference_accuracy_comparison": "not_comparable"}
    write(out / "summary.json", summary)
    print(json.dumps({"status": summary["status"], "issues": issues, "invariant_checks": invariants,
                      "frozen_materials_preserved": preserved}, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        return run(args.input, args.plan, args.out)
    except (ModelError, OSError, json.JSONDecodeError) as exc:
        print("frozen diagnostics: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
