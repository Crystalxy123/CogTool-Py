"""Bounded post-fix reproducibility; saved reference values never enter prediction."""
from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cogtool_py.io import implementation_fingerprint, input_hash, load_project
from scripts.reference_validation_worker import effective_project_hashes
from scripts.run_reference_validation import canonical_sha, read, run_command, sha, verify_trace, write
from scripts.run_visual_integration_validation import verify_complete

LOCAL_CASES = ("single_click", "text_entry", "two_page_wait", "explicit_operators")
OLD_MODES = ("klm_baseline", "motor", "control_prefix")
LEGACY_EXCLUDED = ("program_runtime_s", "implementation", "execution_fingerprint")


def normalize(value, *, across_implementation=False, allow_engine_version_change=False):
    result = deepcopy(value)
    for key in LEGACY_EXCLUDED if across_implementation else ("program_runtime_s",):
        result.pop(key, None)
    if allow_engine_version_change:
        result.pop("engine_version", None)
        result.get("engine", {}).pop("version", None)
    return result


def differences(before, after, path="$"):
    """Keep actual values and paths; never filter events, states or metadata."""
    changed = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(before.keys() | after.keys()):
            where = path + "." + key
            if key not in before or key not in after:
                changed.append({"path": where, "before_present": key in before,
                                "after_present": key in after, "before": before.get(key),
                                "after": after.get(key)})
            else:
                changed.extend(differences(before[key], after[key], where))
    elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        for index, (left, right) in enumerate(zip(before, after)):
            changed.extend(differences(left, right, path + f"[{index}]"))
    elif type(before) is not type(after) or before != after:
        changed.append({"path": path, "before": before, "after": after})
    return changed


def compare(before, after, *, across_implementation=False, allow_engine_version_change=False):
    options = {"across_implementation": across_implementation,
               "allow_engine_version_change": allow_engine_version_change}
    left, right = normalize(before, **options), normalize(after, **options)
    changes = differences(left, right)
    excluded = list(LEGACY_EXCLUDED if across_implementation else ("program_runtime_s",))
    if allow_engine_version_change:
        excluded += ["engine.version", "engine_version"]
    return {"equal": not changes, "changed_fields": changes, "excluded_fields": excluded,
            "before_normalized_sha256": canonical_sha(left), "after_normalized_sha256": canonical_sha(right),
            "input_hash_unchanged": before.get("input_sha256") == after.get("input_sha256"),
            "engine_before": before.get("engine"), "engine_after": after.get("engine"),
            "before_prediction_s": before.get("predicted_time_s"),
            "after_prediction_s": after.get("predicted_time_s")}


def run(run_root: Path, prior_run: Path, out: Path, timeout: int):
    if out.exists():
        raise FileExistsError("Output exists; refusing to overwrite evidence: " + str(out))
    frozen = run_root / "frozen_baseline"
    sources = {name: frozen / (name + ".json") for name in LOCAL_CASES + OLD_MODES}
    sources.update({"NP-B1": frozen / "NP-B1.json",
                    "NP-B2": run_root / "npb2_first_run/candidate_input.json"})
    references = {name: prior_run / "final_regression_02/traces" / name / "repeat_1/result.json"
                  for name in LOCAL_CASES}
    references.update({name: prior_run / "visual_validation_02/legacy" / name / "result.json"
                       for name in OLD_MODES})
    references.update({"NP-B1": frozen / "NP-B1_result/result.json",
                       "NP-B2": run_root / "post_fix_retest/NP-B2_first/result.json"})
    for path in list(sources.values()) + list(references.values()):
        if not path.is_file():
            raise FileNotFoundError(path)
    models = {name: load_project(path) for name, path in sources.items()}
    for name, model in models.items():
        if input_hash(model) != read(references[name])["input_sha256"]:
            raise ValueError(name + ": saved reference has a different effective input hash")
    out.mkdir(parents=True)
    implementation_before = implementation_fingerprint()
    protected_paths = sorted(set(sources.values()) | set(references.values()) |
                             {Path(__file__).resolve(), ROOT / "scripts/reference_validation_worker.py",
                              ROOT / "scripts/run_reference_validation.py",
                              ROOT / "scripts/run_visual_integration_validation.py"})
    protected_before = {str(path): sha(path) for path in protected_paths}
    effective_before = effective_project_hashes(models)
    paths, identities = {}, {}
    for name, model in models.items():
        paths[name] = out / "inputs" / (name + ".json")
        write(paths[name], model.to_dict())
        shutil.copyfile(sources[name], out / "inputs" / (name + ".original.json"))
        identities[name] = {"input_source": str(sources[name]), "input_file_sha256": sha(sources[name]),
                            "saved_effective_input": str(paths[name]), "saved_effective_file_sha256": sha(paths[name]),
                            "input_sha256": input_hash(model), "effective_project_sha256": effective_before[name],
                            "parameters": model.to_dict()["parameters"], "engine": model.engine,
                            "reference_path": str(references[name]), "reference_sha256": sha(references[name])}
    write(out / "input_identity.json", identities)
    policy = {"evidence_kind": "synthetic_software_reproducibility_and_regression",
              "independent_task_cases": ["NP-B1", "NP-B2"], "local_baseline_cases": list(LOCAL_CASES),
              "legacy_modes_are_not_additional_tasks": list(OLD_MODES),
              "same_version_exclusions": ["program_runtime_s"],
              "cross_implementation_exclusions": list(LEGACY_EXCLUDED),
              "NP-B1_only_additional_code_identity_exclusions": ["engine.version", "engine_version"],
              "unfiltered": "all events, state snapshots, parameters, input hashes, scope, warnings, metadata",
              "cross_version_policy": "Every remaining difference is retained and makes the regression comparison unequal.",
              "unknown_reference_policy": "No original rerun is asserted; null is never converted to zero.",
              "reference_values_not_used_as_model_inputs": True, "per_command_timeout_s": timeout,
              "full_suite_run": False, "earlier_frozen_diagnostics": str(run_root / "diagnostic_cases/summary.json")}
    write(out / "comparison_policy.json", policy)
    write(out / "identity_before.json", {"implementation": implementation_before,
                                         "protected_file_sha256": protected_before,
                                         "effective_project_sha256": effective_before})
    commands, issues, summaries = [], [], {}

    def command(label, arguments):
        record = run_command(out, label, [sys.executable, *map(str, arguments)], timeout=timeout)
        record["label"], record["timeout_s"] = label, timeout
        commands.append(record)
        write(out / "commands.json", commands)
        if record["returncode"] != 0:
            issues.append(label + ": command failed with exit " + str(record["returncode"]))
        return record["returncode"] == 0

    def prediction(name, path, destination, label):
        if not command(label, ["-m", "cogtool_py", "predict", path, "--out", destination]):
            return None
        result_path = destination / "result.json"
        if not result_path.is_file():
            issues.append(label + ": successful command did not save result.json")
            return None
        value = read(result_path)
        checks = []
        if value.get("implementation", {}).get("sha256") != implementation_before["sha256"]:
            checks.append("implementation hash differs from run freeze")
        if value.get("input_sha256") != identities[name]["input_sha256"]:
            checks.append("input hash differs from frozen effective input")
        if name in ("NP-B1", "NP-B2"):
            checks.extend(verify_complete(value, implementation_before["sha256"], identities[name]["input_sha256"]))
        elif name in LOCAL_CASES:
            checks.extend(verify_trace(value)["errors"])
        write(destination / "runner_checks.json", {"status": "PASS" if not checks else "FAIL", "issues": checks,
                                                    "result_sha256": sha(result_path)})
        issues.extend(label + ": " + issue for issue in checks)
        return value

    repeated_cases = ("NP-B1", "NP-B2") + LOCAL_CASES
    partners = {"NP-B1": "NP-B2", "NP-B2": "NP-B1"}
    partners.update({name: LOCAL_CASES[(index + 1) % len(LOCAL_CASES)] for index, name in enumerate(LOCAL_CASES)})
    for name in repeated_cases:
        destination = out / "results" / name
        runs = [prediction(name, paths[name], destination / f"repeat_{index}", name + f"_repeat_{index}")
                for index in (1, 2, 3)]
        repeat_checks = [compare(runs[0], result) for result in runs[1:] if runs[0] is not None and result is not None]
        repeat_ok = len(repeat_checks) == 2 and all(check["equal"] for check in repeat_checks)
        saved = out / "inputs" / (name + ".roundtrip.json")
        roundtrip_result = None
        if command(name + "_roundtrip", ["-m", "cogtool_py", "roundtrip", paths[name], "--out", saved]):
            roundtrip_result = prediction(name, saved, destination / "roundtrip", name + "_roundtrip_predict")
        roundtrip_check = compare(runs[0], roundtrip_result) if runs[0] is not None and roundtrip_result is not None else None
        restored_hash = input_hash(load_project(saved)) if saved.is_file() else None
        roundtrip_ok = bool(roundtrip_check and roundtrip_check["equal"] and restored_hash == identities[name]["input_sha256"])
        aba_path = destination / "same_process_A_B_A"
        aba_ok = command(name + "_same_process_A_B_A", [ROOT / "scripts/reference_validation_worker.py",
                         "--a", paths[name], "--b", paths[partners[name]], "--out", aba_path])
        aba = read(aba_path / "summary.json") if (aba_path / "summary.json").is_file() else None
        aba_comparisons = [compare(runs[0], read(aba_path / part / "result.json")) for part in ("1_A", "3_A")
                           if runs[0] is not None and (aba_path / part / "result.json").is_file()]
        aba_ok = bool(aba_ok and aba and aba.get("status") == "PASS" and aba.get("inputs_unmodified") is True
                      and len(aba_comparisons) == 2 and all(value["equal"] for value in aba_comparisons))
        reference_comparison = (compare(read(references[name]), runs[0], across_implementation=True,
                                        allow_engine_version_change=name == "NP-B1") if runs[0] is not None else None)
        if not all((repeat_ok, roundtrip_ok, aba_ok)):
            issues.append(name + ": repeated/roundtrip/A-B-A consistency failed")
        if not reference_comparison or not reference_comparison["equal"]:
            issues.append(name + ": saved-reference comparison differs or is missing")
        summaries[name] = {"case_kind": "official_model_input" if name.startswith("NP-") else "local_baseline_case",
                           "independent_process_count": 3, "repeat_equal": repeat_ok, "repeat_comparisons": repeat_checks,
                           "roundtrip_equal": roundtrip_ok, "roundtrip_comparison": roundtrip_check,
                           "roundtrip_input_sha256": restored_hash, "A_B_A_partner": partners[name],
                           "A_B_A_pass": aba_ok, "A_B_A_comparisons_to_CLI": aba_comparisons,
                           "reference_comparison": reference_comparison,
                           "predicted_time_s": runs[0].get("predicted_time_s") if runs[0] else None,
                           "original_rerun_s": runs[0].get("original_rerun_s") if runs[0] else None,
                           "input_sha256": identities[name]["input_sha256"]}
        write(destination / "summary.json", summaries[name])

    legacy = {}
    for name in OLD_MODES:
        result = prediction(name, paths[name], out / "legacy" / name, "legacy_" + name)
        comparison = compare(read(references[name]), result, across_implementation=True) if result is not None else None
        legacy[name] = comparison
        if not comparison or not comparison["equal"]:
            issues.append("legacy " + name + ": saved-reference comparison differs or is missing")
    write(out / "old_mode_comparisons.json", legacy)
    implementation_after = implementation_fingerprint()
    protected_after = {str(path): sha(path) for path in protected_paths}
    effective_after = effective_project_hashes(models)
    unchanged = (implementation_before == implementation_after and protected_before == protected_after
                 and effective_before == effective_after)
    if not unchanged:
        issues.append("package, validation tools, input/reference files, or effective Project state changed during run")
    write(out / "identity_after.json", {"implementation": implementation_after,
                                        "protected_file_sha256": protected_after,
                                        "effective_project_sha256": effective_after, "all_unchanged": unchanged})
    summary = {"status": "PASS" if not issues else "FAIL", "scope": policy["evidence_kind"],
               "issues": issues, "cases": summaries, "legacy_modes": legacy,
               "command_count": len(commands), "failed_command_count": sum(row["returncode"] != 0 for row in commands),
               "official_input_case_count": 2, "local_baseline_case_count": 4, "legacy_mode_count": 3,
               "repeat_counts_are_not_case_counts": True, "original_rerun_s": None,
               "implementation": implementation_before, "inputs_and_sources_preserved": unchanged,
               "no_accuracy_or_equivalence_claim": True, "full_suite_run": False}
    write(out / "summary.json", summary)
    lines = ["# 冻结修订版复跑", "", "本报告仅检查软件重现性与已保存结果的回归差异，不判定原版等价或准确率。",
             "", f"实际命令 {len(commands)} 条；非零退出 {summary['failed_command_count']} 条。",
             "", "| 案例 | 本次总时长（秒） | 三进程一致 | 保存重载一致 | A→B→A | 已保存结果对照 |",
             "|---|---:|---|---|---|---|"]
    for name, item in summaries.items():
        old = item["reference_comparison"]
        lines.append(f"| {name} | {item['predicted_time_s']} | {item['repeat_equal']} | {item['roundtrip_equal']} | {item['A_B_A_pass']} | {bool(old and old['equal'])} |")
    lines += ["", "旧模式："]
    for name, item in legacy.items():
        lines.append(f"- {name}：完整归一结果一致={bool(item and item['equal'])}；版本字段参与比较。")
    lines += ["", "所有事件和状态均参与比较。逐字段差异与前后值保留在各案例 summary.json。", "",
              "命令日志、原始结果、有效参数、输入与包身份均单独保存。未知原版运行时间保持 null。"]
    if issues:
        lines += ["", "保留的问题：", ""] + ["- " + issue for issue in issues]
    (out / "RETEST_zh.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("retest: " + summary["status"], flush=True)
    return 0 if not issues else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--prior-run", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--timeout", default=120, type=int)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    return run(args.run.resolve(), args.prior_run.resolve(), args.out.resolve(), args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
