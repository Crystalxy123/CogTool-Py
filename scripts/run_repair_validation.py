"""Run all regression tests, real example predictions and bounded phone conversion.

Before evidence is copied with provenance; it is never presented as a new run.
Does not start the incompatible original JVM/CLISP or modify reference material.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import difflib
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_reference_validation import run_command, test_stats, verify_trace
from cogtool_py.io import implementation_fingerprint

EXAMPLES = ("explicit_operators", "single_click", "text_entry", "two_page_wait")
DEFAULT_BASELINE = ROOT / "reports/validation/20260925T104541Z_repair/baseline"
SEMANTIC_RESULT_FIELDS = ("predicted_time_s", "demonstration", "steps", "events",
                          "initial_state", "final_state", "timing_boundary")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stable(result):
    return {k: v for k, v in result.items() if k != "program_runtime_s"}


def current_sources():
    sources = {str(p.relative_to(ROOT)): sha(p)
            for directory in ("cogtool_py", "scripts", "tests", "examples", "docs", "实验数据")
            for p in sorted((ROOT / directory).rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}
    sources.update({p.name: sha(p) for p in ROOT.iterdir() if p.is_file()})
    return sources


def outcomes(path):
    if not Path(path).is_file():
        return {}
    try:
        cases = list(ET.parse(path).getroot().iter("testcase"))
    except ET.ParseError:
        return {}
    result = {}
    for case in cases:
        ident = case.get("classname", "") + "::" + case.get("name", "")
        status = ("FAIL" if case.find("failure") is not None else
                  "ERROR" if case.find("error") is not None else
                  "SKIPPED" if case.find("skipped") is not None else "PASS")
        if ident in result:
            result[ident] = "DUPLICATE_ID"
        else:
            result[ident] = status
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    baseline = args.baseline.resolve()
    if not (baseline / "identity.json").is_file() or not (baseline / "source.tar.gz").is_file():
        parser.error("provide the preserved pre-repair baseline directory")
    out = (args.out or ROOT / "reports/validation" /
           datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_repaired")).resolve()
    if out == baseline or baseline in out.parents:
        parser.error("output cannot be inside preserved baseline evidence")
    if out.exists():
        parser.error("output already exists; choose a fresh directory to preserve evidence")
    out.mkdir(parents=True)
    start = datetime.now(timezone.utc).isoformat()
    before_identity = read(baseline / "identity.json")
    shutil.copytree(baseline, out / "before")
    write(out / "before/provenance.json", {
        "kind": "preserved_pre_repair_execution_not_a_new_run",
        "original_directory": str(baseline), "source_archive_sha256": sha(baseline / "source.tar.gz"),
        "original_created_at_utc": before_identity["created_at_utc"]})
    hashes = current_sources()
    write(out / "snapshot/identity.json", {
        "created_at_utc": start, "executable": sys.executable, "python": sys.version,
        "platform": platform.platform(), "machine": platform.machine(),
        "implementation": implementation_fingerprint(), "source_hashes": hashes,
        "dependencies": {p.metadata["Name"]: p.version for p in importlib.metadata.distributions()}})
    with tarfile.open(out / "snapshot/repaired_source.tar.gz", "w:gz") as archive:
        for name in hashes:
            archive.add(ROOT / name, arcname=name, recursive=False)
    commands, issues = [], []
    write(out / "comparison_config.json", {
        "written_before_comparison": True, "normal_example_prediction_equality": "exact",
        "steps_events_states_equality": "exact", "repeat_equality_excludes": ["program_runtime_s"],
        "trace_internal_tolerance_s": 1e-9, "basis": "floating-point representation, not behavior accuracy",
        "randomness": "deterministic serial klm_baseline", "seed": None,
        "official_equivalence": "not_evaluated_without_aligned_original_rerun"})
    commands.append(run_command(out, "01_previous_diagnostics",
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-o", "junit_family=legacy", "tests/reference_validation/test_diagnostics.py",
         "--junitxml", str(out / "logs/diagnostics.xml")],
        extra_env={"COGTOOL_DIAGNOSTICS_DIR": str(out / "diagnostics")}))
    commands.append(run_command(out, "02_full_suite",
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-o", "junit_family=legacy", "tests", "--junitxml", str(out / "logs/full_suite.xml")]))
    comparisons = []
    for index, case in enumerate(EXAMPLES):
        try:
            path = ROOT / "examples" / (case + ".json")
            results = []
            for repeat in range(1, 4):
                dest = out / "traces" / case / f"repeat_{repeat}"
                record = run_command(out, f"{case}_repeat_{repeat}",
                    [sys.executable, "-m", "cogtool_py", "predict", str(path), "--out", str(dest)])
                commands.append(record)
                if record["returncode"] == 0 and (dest / "result.json").is_file():
                    results.append(read(dest / "result.json"))
            saved = out / "roundtrip" / (case + ".json")
            commands.append(run_command(out, f"{case}_save_reload",
                [sys.executable, "-m", "cogtool_py", "roundtrip", str(path), "--out", str(saved)]))
            roundtrip_dir = out / "traces" / case / "roundtrip"
            commands.append(run_command(out, f"{case}_roundtrip_prediction",
                [sys.executable, "-m", "cogtool_py", "predict", str(saved), "--out", str(roundtrip_dir)]))
            aba_dir = out / "traces" / case / "same_process_A_B_A"
            commands.append(run_command(out, f"{case}_same_process_A_B_A",
                [sys.executable, str(ROOT / "scripts/reference_validation_worker.py"),
                 "--a", str(path), "--b", str(ROOT / "examples" / (EXAMPLES[(index + 1) % 4] + ".json")),
                 "--out", str(aba_dir)]))
            old = read(baseline / "examples" / case / "result.json")
            row = {"case_id": case, "input_file": str(path), "input_file_sha256": sha(path),
                   "before": old, "after": results[0] if results else None,
                   "independent_process_runs": 3, "successful_prediction_invocations": len(results),
                   "reproducible": len(results) == 3 and all(stable(r) == stable(results[0]) for r in results),
                   "roundtrip_unchanged": bool(results) and (roundtrip_dir / "result.json").is_file() and
                       stable(read(roundtrip_dir / "result.json")) == stable(results[0]),
                   "A_B_A": read(aba_dir / "summary.json") if (aba_dir / "summary.json").is_file() else None}
            row["semantic_fields_unchanged"] = bool(results) and all(old[k] == results[0][k] for k in SEMANTIC_RESULT_FIELDS)
            row["effective_parameter_values_unchanged"] = bool(results) and all(
                all(value == results[0]["parameters"][name].get(field) for field, value in parameter.items())
                for name, parameter in old["parameters"].items())
            row["content_hash_changed"] = bool(results) and old["input_sha256"] != results[0]["input_sha256"]
            row["local_trace_checks"] = [verify_trace(r) for r in results]
            row["status"] = "PASS" if (row["reproducible"] and row["roundtrip_unchanged"] and
                row["semantic_fields_unchanged"] and row["effective_parameter_values_unchanged"] and
                row["A_B_A"] and row["A_B_A"]["status"] == "PASS" and
                all(r["status"] == "PASS" for r in row["local_trace_checks"])) else "FAIL"
            comparisons.append(row)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Preserve malformed/missing output as a case failure, and continue
            # other independent cases. Programming errors outside these input/
            # serialization boundaries are not swallowed.
            error = {"case_id": case, "type": type(exc).__name__, "message": str(exc),
                     "traceback": traceback.format_exc()}
            write(out / "logs" / (case + "_report_error.json"), error)
            comparisons.append({"case_id": case, "before": None, "after": None,
                                "status": "FAIL", "report_error": error})
    write(out / "local_before_after.json", comparisons)
    with (out / "local_before_after.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "before_prediction_s", "after_prediction_s",
            "delta_s", "before_input_sha256", "after_input_sha256", "status"])
        writer.writeheader()
        for row in comparisons:
            old, new = row["before"] or {}, row["after"]
            writer.writerow({"case_id": row["case_id"], "before_prediction_s": old.get("predicted_time_s"),
                "after_prediction_s": new["predicted_time_s"] if new else None,
                "delta_s": new["predicted_time_s"] - old["predicted_time_s"] if new and old else None,
                "before_input_sha256": old.get("input_sha256"),
                "after_input_sha256": new["input_sha256"] if new else None, "status": row["status"]})
    commands.append(run_command(out, "03_phone_conversion",
        [sys.executable, str(ROOT / "scripts/convert_phone_case.py"), "--out", str(out / "official")]))
    official = None
    try:
        official = read(out / "official/summary.json")
        prediction = read(out / "official/NP-B1/python_prediction/result.json")
        value = official["diagnostic_python_prediction_s"]
        if not (official["status"] == "DIAGNOSTIC_ONLY" and official["selected_case_id"] == "NP-B1"
                and isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)
                and value == prediction["predicted_time_s"] and official["original_rerun_s"] is None
                and official["original_equivalence_claim"] is False
                and [s["op"] for s in prediction["demonstration"]] == ["menu_select"]
                and [s["op"] for s in prediction["steps"]] ==
                    ["point", "right_click", "think", "point", "click", "transition"]
                and verify_trace(prediction)["status"] == "PASS"):
            issues.append("official diagnostic output failed evidence/semantic checks")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        issues.append("missing/invalid official diagnostic output: " + str(exc))
    # The converter records source extraction and separate diagnostic predictions.
    official_files = [str(p.relative_to(out)) for p in sorted((out / "official").rglob("*")) if p.is_file()]
    diagnostics = test_stats(out / "logs/diagnostics.xml")
    full_suite = test_stats(out / "logs/full_suite.xml")
    original_diagnostics = test_stats(baseline / "original_9_failures.xml")
    old_outcomes = outcomes(baseline / "original_9_failures.xml")
    new_outcomes = outcomes(out / "logs/diagnostics.xml")
    original_failure_ids = [name for name, status in old_outcomes.items() if status == "FAIL"]
    resolved = [name for name in original_failure_ids if new_outcomes.get(name) == "PASS"]
    write(out / "defect_regression_mapping.json", [
        {"test_id": name, "before": old_outcomes[name], "after": new_outcomes.get(name, "MISSING"),
         "resolved": new_outcomes.get(name) == "PASS"} for name in original_failure_ids])
    if (diagnostics.get("status") != "executed" or diagnostics.get("collected") != 18
            or set(old_outcomes) != set(new_outcomes) or len(original_failure_ids) != 9):
        issues.append("original diagnostic tests not fully executed")
    if any(status != "PASS" for status in new_outcomes.values()):
        issues.append("original diagnostics contain a failure/error/skip/duplicate")
    if full_suite.get("status") != "executed":
        issues.append("full test suite not executed")
    if full_suite.get("skipped") != 3 or full_suite.get("xfailed") != 0:
        issues.append("full suite skip/xfail count differs from the three unavailable original references")
    issues += ["command failed: " + str(r["command"]) for r in commands if r["returncode"]]
    issues += ["local case failed: " + r["case_id"] for r in comparisons if r["status"] != "PASS"]
    if current_sources() != hashes:
        issues.append("source files changed during run")
    before_hashes = before_identity["hashes"]
    modified = sorted(name for name in before_hashes if not (ROOT / name).is_file() or sha(ROOT / name) != before_hashes[name])
    added = sorted(set(hashes) - set(before_hashes))
    patches = []
    with tarfile.open(baseline / "source.tar.gz") as archive:
        for name in modified:
            if not name.endswith((".py", ".toml", ".md", ".json")):
                continue
            old = archive.extractfile(name).read().decode("utf-8")
            new = (ROOT / name).read_text(encoding="utf-8") if (ROOT / name).is_file() else ""
            patches.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                                fromfile="before/" + name, tofile="after/" + name))
    (out / "changes.patch").write_text("".join(patches), encoding="utf-8")
    summary = {"baseline_diagnostics": original_diagnostics, "diagnostics": diagnostics,
        "full_suite": full_suite, "original_failures_resolved": len(resolved),
        "resolved_failure_ids": resolved, "local_cases": len(comparisons),
        "local_cases_passed": sum(r["status"] == "PASS" for r in comparisons),
        "official_files": official_files, "official_diagnostic": official, "original_rerun_executed": False,
        "official_equivalence_pass_rate": None, "issues": issues}
    write(out / "run_manifest.json", {"run_id": out.name, "started_at_utc": start,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(), "invocation": sys.argv,
        "baseline_provenance": str(baseline), "commands": commands, "summary": summary,
        "modified_files": modified, "added_files": added, "implementation": implementation_fingerprint(),
        "original_environment": {"action": "reuse_prior_diagnostic_evidence; no repeated startup",
            "evidence_path": str(ROOT / "reports/validation/20260925T103514Z/diagnostics/original_environment.json")},
        "returncode": 1 if issues else 0})
    lines = ["# CogTool-Py 修复与官方任务转换实测", "",
        f"原来的9项失败，本次解决 {len(resolved)} 项；18项诊断中 {diagnostics.get('passed', 0)} 通过、{diagnostics.get('failed', 0)} 失败。",
        f"全套测试 {full_suite.get('passed', 0)} 通过、{full_suite.get('failed', 0)} 失败、{full_suite.get('skipped', 0)} 跳过。原版证据不足的跳过项不算通过。",
        f"四个正常案例成功验收 {summary['local_cases_passed']}/4：各3次独立预测、保存重载、同进程A→B→A。", "",
        "## 正常案例前后对照", "",
        "| 案例 | 修复前秒数 | 修复后秒数 | 状态 |", "|---|---:|---:|---|"]
    for row in comparisons:
        lines.append(f"| {row['case_id']} | {(row['before'] or {}).get('predicted_time_s', '缺失')} | "
                     f"{row['after']['predicted_time_s'] if row['after'] else '未执行'} | {row['status']} |")
    lines += ["", "完整有效参数、内容哈希、示范、生成步骤和事件前后值见local_before_after.json。"
        "正常输入的时间和动作语义要求完全相同，没有调整时间容差或参考数字。内容哈希升级为完整有效参数、来源及默认版本；代码身份另外记录。",
        "", "## 缺陷与回归对应", "",
        "| 缺陷 | 修复位置 | 保留的诊断/新增回归 |", "|---|---|---|",
        "| 未知op、快捷键、错误单位、非法控件 | validation.py / models.py / generator.py | 原未知op、shortcut、unit、widget诊断及test_api_validation.py |",
        "| 参数修改不入hash、保存丢失 | models.py ParameterSet / io.py | 原identity、roundtrip诊断迁移；test_parameter_lifecycle.py |",
        "| 零宽零距离、空键、ScriptStep误传 | validation.py / engine.py point_time | 原zero_width、empty_keys、expanded_script诊断 |",
        "", "原诊断测试名字和数量保留。两项参数修改用例现在先断言直接写入被拒绝，"
        "再通过合法override验证数值变化、hash变化和往返一致；单位诊断同时检查冻结和构造/覆盖拒绝。"
        "负时长仍被拒绝，错误提前到输入字段。旧schema测试改为拒绝3，保存断言改为2，"
        "对应明确的v1→v2契约升级；不是删除失败、skip/xfail或放宽断言。",
        "", "## 官方任务与边界", "",
        f"本次官方诊断状态：{(official or {}).get('status', '未完成')}。NP-B1论文发表值 "
        f"{(official or {}).get('published_prediction_s')} s；历史缓存 "
        f"{(official or {}).get('archived_prediction_s')} s（archived_reference）；本次原版重跑 null；"
        f"本次Python诊断值 {(official or {}).get('diagnostic_python_prediction_s')} s。",
        "优先提取NP-A1，保留层级菜单/hover和无duration的LookAt精确阻塞。"
        "NP-B1没有这些缺失动作，依据输入完整度选择它打通单层右键菜单。"
        "转换器从真实对象引用、几何与手部初态产生输入；初始鼠标(0,0)是2014源码的条件默认，2009缓存初态尚未证实。",
        "官方提取、字段映射、阻塞、归档参考、可执行输入及实际运行记录位于official/。"
        "论文值、历史缓存、本次原版值和Python诊断值分别保存；旧缓存和旧trace没有作为引擎计算输入。",
        "当前仍是klm_baseline串行引擎。单层menu_select保留右键并按源码规则展开，"
        "未实现完整ACT-R视觉/运动准备与资源重叠。诊断预测不表示原版等价或预测精度。",
        "唯一最重要的后续阻塞：取得匹配原模型版本、参数和计时边界的原版重新计算轨迹，"
        "才能对已可运行输入做严格差分。导出要求见docs/original_export_zh.md。",
        "", "## 证据与复跑", "",
        "before/是带来源的本轮修复前实测副本；snapshot/为修复后源码快照。"
        "旧报告未覆盖。本轮未重复启动已知不兼容的JVM/CLISP，未上传资料或改变全局环境。",
        "修改与新增文件：", "", *["- " + name for name in modified + added], "",
        "新报告目录内每个文件和SHA-256见artifact_inventory.json；差异见changes.patch。",
        "", "在项目目录复跑（每次产生新目录）：", "",
        "    .venv/bin/python scripts/run_repair_validation.py", "",
        f"本次总退出码：{1 if issues else 0}。异常：{json.dumps(issues, ensure_ascii=False)}。"]
    (out / "REPORT_zh.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write(out / "artifact_inventory.json", {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob("*")) if p.is_file()})
    print(json.dumps({"out": str(out), "resolved": len(resolved), "full_suite": full_suite,
                      "local_cases_passed": summary["local_cases_passed"], "issues": issues}, ensure_ascii=False, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
