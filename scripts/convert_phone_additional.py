#!/usr/bin/env python3
"""Extract NP-B2's own demonstration, then preserve its first frozen CLI run.

No cached result, saved generated script, trace, published value or NP-B1 task
is consulted. Only effective parameters and control policy come from the frozen
NP-B1 input. The whole ZIP is parsed as data; semantic dereferencing is audited
and explicitly excludes all reference-result fields. This is a narrow converter.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cogtool_py.io import implementation_fingerprint
from scripts.convert_phone_case import ConversionError, app_for, parent_chain, read_phone, widget
from scripts.inspect_original_models import CODE_COMMIT, Graph, classname, field


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


class InputGraph(Graph):
    """Reject semantic access to result/cache fields, while recording input reads."""
    forbidden = {"taskTime", "traceLines", "errorLines", "stepStates", "result", "results", "script", "scripts"}

    def __init__(self, root):
        super().__init__(root)
        self.accesses = []

    def check(self, node, var):
        if var in self.forbidden or classname(node) in {"TimePredictionResult", "APredictionResult", "Script"}:
            raise ConversionError(f"Reference/cache access forbidden before first frozen run: {classname(node)}.{var}")
        self.accesses.append({"object_id": node.get("id") if node is not None else None,
                              "class": classname(node), "field": var})

    def get(self, node, var):
        self.check(node, var)
        return super().get(node, var)

    def value(self, node, var):
        self.check(node, var)
        return super().value(node, var)

    def name(self, node):
        node = self.resolve(node)
        self.check(node, "name")
        return super().name(node)


def scene(graph, frame):
    originals = graph.entries(graph.get(frame, "widgets"))
    converted = [widget(graph, node) for node in originals]
    groups, mappings = {}, []
    for node, item in zip(originals, converted):
        parent_group = graph.get(node, "parentGroup")
        if parent_group is not None and parent_group.tag != "null":
            if classname(parent_group) != "SimpleWidgetGroup":
                raise ConversionError("Only direct SimpleWidgetGroup scene extraction is supported")
            groups[parent_group.get("id")] = parent_group
        mappings.append({"python_field": f"design.frames[f{frame.get('id')}].widgets[{item['id']}]",
            "source_object_id": node.get("id"), "source_class": classname(node),
            "fields": {"name": "ATransitionSource.name", "label": "Widget.title",
                       "parent": "MenuItem.parent idref", "kind": "Widget.widgetType",
                       "x/y/width/height": "Widget.shape/AShape.r/DoubleRectangle"},
            "center_from_source_rule": [item["x"] + math.floor(item["width"] / 2),
                                        item["y"] + math.floor(item["height"] / 2)],
            "persisted_widget_order": len(mappings)})
    auxiliary, evidence = [], []
    original_ids = {node.get("id") for node in originals}
    for ident, group in sorted(groups.items(), key=lambda pair: int(pair[0])):
        members = graph.entries(graph.get(group, "members"))
        if not members or any(member.get("id") not in original_ids for member in members):
            raise ConversionError("Group has absent or out-of-frame members")
        rects = [graph.target(member)["geometry"] for member in members]
        x, y = min(r["x"] for r in rects), min(r["y"] for r in rects)
        right, bottom = max(r["x"] + r["width"] for r in rects), max(r["y"] + r["height"] for r in rects)
        bounds = {"x": x, "y": y, "width": right-x, "height": bottom-y}
        source = {"object_id": ident, "class": classname(group), "members": [m.get("id") for m in members],
                  "bounds": bounds, "geometry_rule": "union original member bounds then x+floor(width/2),y+floor(height/2)",
                  "source_commit": CODE_COMMIT,
                  "unknown_symbol_reason": "Anonymous GROUP [iN] numbering depends on unexecuted Java emission order"}
        auxiliary.append({"id": "g"+ident, "frame": "f"+frame.get("id"),
                          "x": x+math.floor(bounds["width"]/2), "y": y+math.floor(bounds["height"]/2),
                          "source": json.dumps(source, ensure_ascii=False, sort_keys=True)})
        evidence.append(source)
    return {"id": "f"+frame.get("id"), "name": graph.name(frame), "widgets": converted}, auxiliary, evidence, mappings


def extract(policy_path):
    raw, provenance = read_phone()
    graph = InputGraph(raw.root)
    app = app_for(graph, "Pop-Up", "Look up two numbers")
    demo, task = graph.get(app, "demonstration"), graph.get(app, "task")
    initial, start = graph.get(demo, "initialState"), graph.get(demo, "startFrame")
    initial_saved = {key: graph.value(initial, key) for key in ("mouseHand", "rightHandLoc", "leftHandLoc", "modifiers")}
    if initial_saved != {"mouseHand": True, "rightHandLoc": "M", "leftHandLoc": "K", "modifiers": 0}:
        raise ConversionError("NP-B2 initial hand state differs from the supported interpretation")
    initial_refs = {key: graph.get(initial, key).get("id") if graph.get(initial, key) is not None else None
                    for key in ("lastClickedWidget", "lastMovedToWidget", "lastLookedAtWidget")}
    if any(value is not None for value in initial_refs.values()):
        raise ConversionError("Nonempty saved initial widget state needs explicit interpretation")
    frame, auxiliary, groups, mappings = scene(graph, start)
    records, steps, transitions, seen_transitions = [], [], [], set()
    for index, node in enumerate(graph.entries(graph.get(demo, "steps"))):
        if classname(node) != "TransitionScriptStep":
            raise ConversionError("NP-B2 narrow extraction encountered a non-transition demonstration step")
        transition = graph.get(node, "transition")
        action, target = graph.get(transition, "action"), graph.get(transition, "source")
        current, destination = graph.get(node, "currentFrame"), graph.get(transition, "destination")
        if current.get("id") != start.get("id") or destination.get("id") != start.get("id"):
            raise ConversionError("NP-B2 additional frame cannot be silently dropped")
        if (classname(action) != "ButtonAction" or graph.value(action, "button") != "0" or
                graph.value(action, "pressType") != "0" or graph.value(action, "modifiers") != 0):
            raise ConversionError("Unsupported original demonstration action")
        chain = parent_chain(graph, target)
        if classname(target) != "MenuItem" or len(chain) != 2 or chain[1]["class"] != "ContextMenu":
            raise ConversionError("NP-B2 action is not a direct ContextMenu-to-MenuItem selection")
        parent = graph.index[chain[1]["object_id"]]
        explicit = graph.value(parent, "WidgetType.contextMenuAction")
        authority = graph.get(parent, "authority")
        if explicit not in (None, 0) or (authority is not None and authority.tag != "null"):
            raise ConversionError("Context-menu opening is not the default right-click path")
        record = {**graph.step(node), "demonstration_index": index, "current_frame_object_id": current.get("id"),
                  "destination_frame_object_id": destination.get("id"), "target_parent_chain": chain,
                  "menu_opening_evidence": {"explicit_context_menu_action": explicit,
                    "authority_object_id": None, "default": "right_click",
                    "source": "WidgetAttributes.java:333-347,453-455"}}
        records.append(record)
        tid = "t"+transition.get("id")
        steps.append({"op": "menu_select", "target": "w"+target.get("id"), "transition": tid})
        if tid not in seen_transitions:
            transitions.append({"id": tid, "from_frame": frame["id"], "target": "w"+target.get("id"),
                                "to_frame": frame["id"], "delay_s": graph.value(transition, "delayInSecs")})
            seen_transitions.add(tid)
        mappings.append({"python_field": f"tasks[0].demonstration.steps[{index}]",
                         "source_object_id": node.get("id"), "transition_object_id": transition.get("id"),
                         "action_object_id": action.get("id"), "item_object_id": target.get("id"),
                         "context_menu_object_id": parent.get("id"), "input": copy.deepcopy(steps[-1]),
                         "meaning": "one own demonstrated action; generated automatic steps are not replayed"})
    if not records:
        raise ConversionError("No own NP-B2 demonstration steps")
    # This file is not copied as a task. Only the effective parameter and control
    # profile fields are read; the NP-B2 scene above was independently rebuilt.
    frozen = json.loads(policy_path.read_text())
    if frozen["engine"] != "cogtool_control_prefix_experimental" or frozen["control"]["profile"] != "source_2014_defaults" or frozen["control"]["execution_scope"] != "integrated_task":
        raise ConversionError("Expected frozen normal 2014 integrated policy")
    control = copy.deepcopy(frozen["control"])
    control["auxiliary_locations"] = auxiliary
    candidate = {"schema_version": 2, "id": "NP-B2-frozen-additional", "name": "NP-B2 own official demonstration / frozen integrated diagnostic",
                 "engine": frozen["engine"], "parameters": copy.deepcopy(frozen["parameters"]), "control": control,
                 "design": {"id": "phone-NP-B2", "name": "Pop-Up", "coordinate_unit": "px", "frames": [frame], "transitions": transitions},
                 "tasks": [{"id": "NP-B2", "name": graph.name(task), "demonstration": {
                     "initial": {"frame": frame["id"], "mouse": [0, 0], "mouse_hand": "right", "hand": "mouse", "focus": None}, "steps": steps}}]}
    extraction = {"case_id": "NP-B2", "source": provenance, "source_design": "Pop-Up", "source_task": graph.name(task),
                  "task_application_object_id": app.get("id"), "demonstration_object_id": demo.get("id"),
                  "initial_state_object_id": initial.get("id"), "start_frame_object_id": start.get("id"),
                  "initial_saved": initial_saved, "initial_widget_references": initial_refs,
                  "initial_derived": {"mouse": [0, 0], "eye": [0, 0], "source_commit": CODE_COMMIT,
                      "sources": ["cogtool-actr.lisp:1150-1152", "emma.lisp:775-783"],
                      "normal_wrapper_startup_clear": True, "archived_2009_initial_state_verified": False},
                  "demonstration_steps": records, "scene_groups": groups,
                  "scene_policy": "Full own start frame widget order and all direct groups; ordinary emitVirtualFrames=false, no menu visibility filtering",
                  "not_used_to_construct_input": ["TimePredictionResult.taskTime", "traceLines", "saved Script.stepStates", "published results", "NP-B1 task/demo"],
                  "same_frame_as_NPB1": "Both original TaskApplications reference the same design Frame6; NP-B2 actions are independently dereferenced",
                  "frozen_parameter_policy": {"path": str(policy_path.relative_to(ROOT)), "sha256": sha(policy_path.read_bytes()),
                      "copied_fields": ["engine", "parameters", "control except freshly extracted auxiliary_locations"],
                      "parameter_values_and_provenance_changed": False},
                  "reference_access_status": "no semantic reference result/cache/trace access before first frozen prediction"}
    return candidate, extraction, mappings, graph.accesses


def execute(command, directory, name):
    started, wall_start = now(), time.perf_counter()
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
        stdout, stderr, code, outcome = result.stdout, result.stderr, result.returncode, "completed"
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, code, outcome = exc.stdout or "", exc.stderr or "", None, "timeout"
        stdout = stdout.decode(errors="replace") if isinstance(stdout, bytes) else stdout
        stderr = stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr
    (directory / f"{name}.stdout.txt").write_text(stdout)
    (directory / f"{name}.stderr.txt").write_text(stderr)
    record = {"command": command, "started_at_utc": started, "finished_at_utc": now(), "returncode": code,
              "outcome": outcome, "wall_clock_runtime_s": time.perf_counter()-wall_start, "timeout_s": 30,
              "stdout": f"{name}.stdout.txt", "stderr": f"{name}.stderr.txt"}
    write(directory / f"{name}.process.json", record)
    return record


def convert(out, policy_path, plan_path):
    out, policy_path, plan_path = out.resolve(), policy_path.resolve(), plan_path.resolve()
    if not out.is_relative_to(ROOT / "reports") or out.exists():
        raise ConversionError("Output must be a new path under workspace reports; no overwrite")
    plan = json.loads(plan_path.read_text())
    before = implementation_fingerprint()
    expected = plan["frozen_implementation"]["sha256"]
    if before["sha256"] != expected:
        raise ConversionError("Core implementation differs from frozen validation plan")
    candidate, extraction, mappings, accesses = extract(policy_path)
    out.mkdir(parents=True)
    write(out / "candidate_input.json", candidate)
    write(out / "extraction.json", extraction)
    write(out / "field_mapping.json", {"fields": mappings, "source_commit": CODE_COMMIT})
    write(out / "input_field_access_audit.json", {"forbidden_fields": sorted(InputGraph.forbidden),
        "accesses": accesses, "whole_archive_parsed_as_data": True, "reference_fields_semantically_read": False,
        "policy_input_reads": ["engine", "parameters", "control"],
        "note": "Object IDs/classes are indexed across PERSIST; no result values or generated step contents are dereferenced."})
    manifest = {"phase": "input_saved_before_first_predict", "at_utc": now(), "case_id": "NP-B2",
                "validation_plan": str(plan_path.relative_to(ROOT)), "validation_plan_sha256": sha(plan_path.read_bytes()),
                "frozen_implementation": before, "candidate_json_sha256": sha((out/"candidate_input.json").read_bytes()),
                "converter_sha256": sha(Path(__file__).read_bytes()), "read_new_reference_results": False,
                "original_rerun_s": None}
    write(out / "before_first_prediction.json", manifest)
    command = [sys.executable, "-m", "cogtool_py"]
    validation = execute(command+["validate", str(out/"candidate_input.json")], out, "first_validate")
    # Always make the actual first predict attempt, including validation rejects.
    prediction = execute(command+["predict", str(out/"candidate_input.json"), "--out", str(out/"prediction")], out, "first_predict")
    after = implementation_fingerprint()
    unchanged = before == after and after["sha256"] == expected
    result_path = out/"prediction/result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else None
    stderr = (out/"first_predict.stderr.txt").read_text()
    status = result.get("completion_status", "error") if result else (
        "unsupported" if "unsupported repeated menu selection" in stderr else "error")
    summary = {"case_id": "NP-B2", "development_role": "frozen_additional_case", "not_strictly_blind": True,
               "execution_status": status, "comparison_status": "not_run", "reference_kind": "none",
               "reference_access_before_first_run": False, "first_failure_preserved": prediction["returncode"] != 0,
               "predicted_time_s": result.get("predicted_time_s") if result else None,
               "original_rerun_s": None, "result_path": "prediction/result.json" if result else None,
               "first_error": stderr.strip() if prediction["returncode"] != 0 else None,
               "frozen_core_unchanged": unchanged, "implementation_before": before, "implementation_after": after,
               "processes": [validation, prediction], "continuous_single_task": True,
               "reset_between_queries": False, "input_steps": candidate["tasks"][0]["demonstration"]["steps"],
               "no_input_or_engine_bypass": True, "model_input_sha256": result.get("input_sha256") if result else None}
    write(out / "summary.json", summary)
    (out / "EXTRACTION_zh.md").write_text(
        "# NP-B2 首次冻结输入与执行\n\n"
        f"原始 TaskApplication {extraction['task_application_object_id']} / Demonstration {extraction['demonstration_object_id']} / InitialState {extraction['initial_state_object_id']}。"
        "独立解析自身示范，按原顺序保留两个菜单选择；同一个任务连续执行，不在两次查询间重置状态。"
        "场景全部控件和组来自该任务实际引用的起始 frame；与 NP-B1 共享原始 frame 不等于复制 NP-B1 任务。\n\n"
        "只从冻结 NP-B1 输入读取完整有效参数和正常 2014 控制策略；没有读取 NP-B2 缓存、轨迹、生成脚本或发表数值。"
        "XML 全文仅作为对象表解析；逐字段语义访问日志和参考字段拒绝清单另存。\n\n"
        f"首次执行状态：{status}；预测时间：{summary['predicted_time_s']}；核心冻结身份不变：{unchanged}。"
        "validate 与 predict 都实际运行，原始 stdout/stderr 和进程记录均保留。拒绝不以拆分任务、复制第一次结果或绕过验证替代。"
        "尚未进行任何参考结果比较；unsupported 不计为精度通过，null 不当作零。\n", encoding="utf-8")
    if not unchanged:
        raise ConversionError("Core implementation changed during first frozen execution; result retained but invalid freeze")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--policy-input", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args()
    try:
        summary = convert(args.out, args.policy_input, args.plan)
        print(json.dumps({key: summary[key] for key in ("case_id", "execution_status", "predicted_time_s", "frozen_core_unchanged")}, ensure_ascii=False))
        return 0
    except (ConversionError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"Additional phone extraction failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
