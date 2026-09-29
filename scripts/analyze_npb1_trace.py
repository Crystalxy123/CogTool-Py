"""Lossless, offline analysis of an archived NP-B1 ACT-R trace.

Point events are observations, never adjacent-row durations. Only an unambiguous
same-name PRODUCTION-SELECTED/PRODUCTION-FIRED pair gets a reference duration.
Motor phases are linked by a bounded single-execution/two-stage preparation
state machine; ambiguous or unsupported events remain visible and unmatched.
No original engine is executed, and no parameter is fitted to the cached total.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
TIMED = re.compile(rf"^\s*({NUMBER})\s+(\S+)\s+(.*?)\s*$")
PARAMETER = re.compile(r"^:([A-Z0-9-]+)\s+(.*?)\s+default:\s*(.*?)\s+:\s*(.*)$")
MODULE = re.compile(r"^:?(\S+) module\s*$")
PRODUCTION = re.compile(r"^PRODUCTION-(SELECTED|FIRED)\s+(\S+)\s*$", re.I)
TOLERANCE = Decimal("0.0000002")


class TraceError(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atom(raw):
    """Parse only scalar literals; Lisp forms are preserved, never evaluated."""
    if re.fullmatch(NUMBER, raw):
        value = float(raw)
        return value if math.isfinite(value) else raw
    return {"T": True, "NIL": None}.get(raw, raw)


def parse_trace(text):
    records, parameters, events = [], [], []
    module = None
    for line_number, raw in enumerate(text.splitlines(keepends=True), 1):
        content = raw.rstrip("\r\n")
        row = {"line_number": line_number, "raw": raw, "kind": "unknown"}
        match = PARAMETER.match(content)
        if match:
            name, observed, default, description = match.groups()
            parameter = {"name": name, "module": module, "observed": atom(observed),
                         "observed_raw": observed, "default": atom(default), "default_raw": default,
                         "description": description, "source": {"kind": "archived_trace_parameter_printout", "line_number": line_number},
                         "current_runtime_default_claim": False}
            parameters.append(parameter)
            row.update(kind="parameter", parameter_name=name)
        elif (match := MODULE.match(content)):
            module = match.group(1)
            row.update(kind="module_header", module=module)
        elif (match := TIMED.match(content)):
            stamp, event_module, message = match.groups()
            value = float(stamp)
            if not math.isfinite(value) or value < 0:
                raise TraceError(f"line {line_number}: invalid timestamp {stamp}")
            event = {"event_id": f"L{line_number}", "line_number": line_number,
                     "timestamp_s": value, "timestamp_text": stamp, "module": event_module,
                     "message": message, "event_type": "point_in_time", "duration_s": None}
            events.append(event)
            row.update(kind="event", event_id=event["event_id"])
        elif re.fullmatch(NUMBER, content.strip()):
            row.update(kind="scalar_output", value_raw=content.strip(), value=atom(content.strip()))
        elif not content.strip():
            row["kind"] = "blank"
        elif set(content.strip()) == {"-"}:
            row["kind"] = "separator"
        records.append(row)
    return {"raw_lines": records, "parameters": parameters, "events": events,
            "lossless_raw_reconstruction": "".join(row["raw"] for row in records) == text}


def pair_productions(events):
    pending, pairs, unmatched = {}, [], []
    for event in events:
        match = PRODUCTION.match(event["message"]) if event["module"] == "PROCEDURAL" else None
        if not match:
            continue
        phase, name = match.groups()
        if phase.upper() == "SELECTED":
            pending.setdefault(name, []).append(event)
            continue
        selected = pending.pop(name, [])
        if len(selected) != 1:
            unmatched.extend({"event_id": item["event_id"], "reason": "ambiguous or missing same-name selection"}
                             for item in [*selected, event])
            continue
        start = selected[0]
        duration = Decimal(event["timestamp_text"]) - Decimal(start["timestamp_text"])
        if duration < 0:
            unmatched.extend({"event_id": item["event_id"], "reason": "fired timestamp precedes selection"} for item in (start, event))
            continue
        pairs.append({"production": name, "selected_event_id": start["event_id"], "fired_event_id": event["event_id"],
                      "start_s": start["timestamp_s"], "end_s": event["timestamp_s"], "duration_s": float(duration),
                      "evidence": "unique same-name PROCEDURAL selection and firing; not adjacent-event subtraction"})
    unmatched.extend({"event_id": item["event_id"], "reason": "selected without same-name firing"}
                     for items in pending.values() for item in items)
    return {"pairs": pairs, "unmatched": unmatched}


def link_motor(events):
    actions, unmatched = [], []
    preparing = None
    executing = None
    prepared_click = None
    target = None
    ambiguous_execution = False

    def reject(event, reason):
        unmatched.append({"event_id": event["event_id"], "reason": reason})

    for event in events:
        if event["module"] != "MOTOR":
            continue
        message = event["message"]
        kind = ("cursor_move" if message.startswith("MOVE-CURSOR OBJECT ") else
                "prepare_click" if message.startswith("PREPARE PUNCH ") else
                "click" if message.startswith("CLICK-MOUSE ") else None)
        if kind:
            if preparing is not None or (kind != "prepare_click" and executing is not None):
                reject(event, "overlapping/ambiguous motor request; no ownership inferred")
                if executing is not None and kind != "prepare_click":
                    executing["status"] = "ambiguous_overlapping_execution"
                    ambiguous_execution = True
                continue
            if kind == "cursor_move":
                label = re.search(r'"([^\"]+)"', message)
                target = label.group(1) if label else None
            action = {"action_id": f"motor_{len(actions)}", "kind": kind, "target_label": target,
                      "request_event_id": event["event_id"], "request_s": event["timestamp_s"],
                      "phase_events": {"request": event["event_id"]}, "status": "incomplete",
                      "pairing_basis": "unique pending preparation; separate single execution until FINISH-MOVEMENT",
                      "duration_s": None}
            if kind == "click":
                action["prior_preparation_action_id"] = prepared_click
                action["button_from_trace"] = None
                prepared_click = None
            actions.append(action)
            preparing = action
            if kind != "prepare_click":
                executing = action
        elif message == "PREPARATION-COMPLETE":
            if preparing is None:
                reject(event, "no unique pending motor preparation")
            else:
                preparing["phase_events"]["preparation_complete"] = event["event_id"]
                if preparing["kind"] == "prepare_click":
                    preparing["status"] = "preparation_only_completed"
                    prepared_click = preparing["action_id"]
                preparing = None
        elif message in {"INITIATION-COMPLETE", "FINISH-MOVEMENT"} or message.startswith(("MOVE-CURSOR-ABSOLUTE ", "OUTPUT-KEY ")):
            phase = ("initiation_complete" if message == "INITIATION-COMPLETE" else
                     "finish" if message == "FINISH-MOVEMENT" else "output")
            if ambiguous_execution:
                reject(event, "ambiguous execution ownership after overlapping requests")
            elif executing is None:
                reject(event, "no unique executing motor action")
            elif phase in executing["phase_events"]:
                reject(event, f"duplicate {phase}; ownership not inferred")
            elif phase == "output" and ((executing["kind"] == "cursor_move") != message.startswith("MOVE-CURSOR-ABSOLUTE ")):
                reject(event, "output type does not match executing action")
            elif phase == "initiation_complete" and "preparation_complete" not in executing["phase_events"]:
                reject(event, "missing preparation before motor initiation")
            elif phase in {"output", "finish"} and "initiation_complete" not in executing["phase_events"]:
                reject(event, "missing initiation before motor output/finish")
            else:
                executing["phase_events"][phase] = event["event_id"]
                if phase == "finish":
                    executing["status"] = "completed" if "output" in executing["phase_events"] else "incomplete_missing_output"
                    executing = None
        else:
            reject(event, "motor message outside bounded grammar")
    return {"actions": actions, "unmatched": unmatched,
            "scope": "observed NP-B1 single motor execution, independent PREPARE PUNCH; no general ACT-R queue reconstruction"}


def integrity(parsed, metadata):
    events = parsed["events"]
    stamps = [Decimal(event["timestamp_text"]) for event in events]
    scalar = [row for row in parsed["raw_lines"] if row["kind"] == "scalar_output"]
    cached = metadata.get("cached_prediction_s")
    stop = [event for event in events if re.fullmatch(r"PRODUCTION-FIRED STOP-\d+", event["message"])]
    finish = [event for event in events if event["module"] == "MOTOR" and event["message"] == "FINISH-MOVEMENT"]
    end = [event for event in events if event["message"] == "Stopped because no events left to process"]
    checks = []

    def check(name, result, **details):
        checks.append({"name": name, "status": "not_evaluated" if result is None else "consistent" if result else "inconsistent", **details})

    def near(name, first, second):
        if first is None or second is None:
            check(name, None, first=first, second=second)
        else:
            difference = abs(Decimal(str(first)) - Decimal(str(second)))
            check(name, difference <= TOLERANCE, first=first, second=second, absolute_difference_s=float(difference))

    check("raw_line_preservation", parsed["lossless_raw_reconstruction"])
    check("timestamped_events_present", bool(events))
    check("timestamp_order", all(a <= b for a, b in zip(stamps, stamps[1:])) if events else None)
    check("observed_start_at_zero", stamps[0] == 0 if stamps else None)
    check("task_stop_present", bool(stop))
    check("motor_finish_present", bool(finish))
    check("queue_exhausted_end_present", bool(end))
    check("task_stop_before_or_at_final_motor_finish", stop[-1]["timestamp_s"] <= finish[-1]["timestamp_s"] if stop and finish else None)
    near("last_motor_finish_vs_queue_end", finish[-1]["timestamp_s"] if finish else None, end[-1]["timestamp_s"] if end else None)
    near("trace_end_vs_archived_cache", events[-1]["timestamp_s"] if events else None, cached)
    near("final_scalar_vs_archived_cache", scalar[-1]["value"] if scalar else None, cached)
    return {"checks": checks, "has_inconsistency": any(c["status"] == "inconsistent" for c in checks),
            "start_s": events[0]["timestamp_s"] if events else None, "end_s": events[-1]["timestamp_s"] if events else None,
            "task_stop_events": stop, "last_motor_finish": finish[-1] if finish else None,
            "queue_exhausted_events": end, "final_scalar_output": scalar[-1] if scalar else None,
            "cached_prediction_s": cached, "tolerance_s": float(TOLERANCE),
            "tolerance_basis": "NP-B1 scalar/cache binary-float representation differs from printed millisecond timestamp by 2e-7 s; source-resolution consistency only, not model equivalence",
            "printed_event_timestamp_resolution_s": .001,
            "not_current_original_rerun": True, "equivalence_evaluated": False}


ANCHOR_NAMES = ("point_parent", "open_parent_menu", "think", "point_item", "click_item", "task_end")


def semantic_alignment(parsed, productions, motor, metadata, baseline, experimental=None):
    by_id = {event["event_id"]: event for event in parsed["events"]}
    anchors = {name: {"anchor": name, "reference_event_ids": [], "reference_production_pairs": [],
                      "reference_motor_action_ids": [], "baseline_events": [], "experimental_events": []} for name in ANCHOR_NAMES}
    pair_roles = {"FIND-2": "point_parent", "LOOK-AT-5": "point_parent", "MOVE-MOUSE-7": "point_parent",
                  "PREPARE-CLICK-8": "open_parent_menu", "CLICK-MOUSE-9": "open_parent_menu", "THINK-10": "think",
                  "FIND-11": "point_item", "LOOK-AT-14": "point_item", "MOVE-MOUSE-16": "point_item",
                  "PREPARE-CLICK-17": "click_item", "CLICK-MOUSE-18": "click_item", "STOP-19": "task_end"}
    for pair in productions["pairs"]:
        if (role := pair_roles.get(pair["production"])):
            anchors[role]["reference_production_pairs"].append(pair)
            anchors[role]["reference_event_ids"].extend([pair["selected_event_id"], pair["fired_event_id"]])
    moves = [step for step in metadata.get("saved_generated_steps", []) if step.get("action", {}).get("class") == "MoveMouseAction"]
    targets = {}
    for move, role in zip(moves, ("parent", "item")):
        target = move.get("target", {})
        targets[role] = target
    for action in motor["actions"]:
        role = next((role for role, target in targets.items()
                     if action["target_label"] and action["target_label"].startswith(target.get("name", "") + " in ")), None)
        if role:
            anchor = ("point_" + role if action["kind"] == "cursor_move" else
                      "open_parent_menu" if role == "parent" else "click_item")
            anchors[anchor]["reference_motor_action_ids"].append(action["action_id"])
            anchors[anchor]["reference_event_ids"].extend(action["phase_events"].values())
    for event in parsed["events"]:
        if event["message"] == "Stopped because no events left to process":
            anchors["task_end"]["reference_event_ids"].append(event["event_id"])
        if event["module"] == "VISION":
            for role, target in targets.items():
                token = target.get("name", "").upper() + " IN "
                if target.get("name") and token in event["message"].upper():
                    anchors["point_" + role]["reference_event_ids"].append(event["event_id"])
    for role, anchor in anchors.items():
        ids = sorted(set(anchor["reference_event_ids"]), key=lambda value: by_id[value]["line_number"])
        anchor["reference_event_ids"] = ids
        anchor["reference_point_events"] = [by_id[value] for value in ids]
        anchor["reference_motor_actions"] = [action for action in motor["actions"]
                                               if action["action_id"] in anchor["reference_motor_action_ids"]]
        anchor["reference_duration_s"] = None
        anchor["reference_duration_note"] = "heterogeneous many-to-one semantic group; not an additive or adjacent-row duration"
        anchor["reference_boundary_observations"] = {"first_s": by_id[ids[0]]["timestamp_s"], "last_s": by_id[ids[-1]]["timestamp_s"]} if ids else None
    clicks = [step for step in metadata.get("saved_generated_steps", []) if step.get("action", {}).get("class") == "ButtonAction"]
    for step, anchor in zip(clicks, ("open_parent_menu", "click_item")):
        anchors[anchor]["saved_step_button_evidence"] = {"step_object_id": step["object_id"], "target": step.get("target"),
            "action": step["action"], "trace_button_observed": False,
            "note": "archived generated-step metadata supplies button identity; generic CLICK-MOUSE/DEVICE-CLICK alone does not"}
    unmatched_python = {}
    for label, result in (("baseline", baseline), ("experimental", experimental)):
        if result is None:
            unmatched_python[label] = None
            continue
        steps = {step.get("index", index): step for index, step in enumerate(result.get("steps", []))}
        unmatched_python[label] = []
        for event in result.get("events", []):
            step = steps.get(event.get("step_index"), {})
            op = step.get("op") or event.get("op")
            target = step.get("target") or event.get("target")
            role = next((role for role, item in targets.items() if target == "w" + item.get("object_id", "")), None)
            anchor = ("point_" + role if op == "point" and role else
                      "open_parent_menu" if op == "right_click" else
                      "click_item" if op == "click" and role == "item" else
                      "think" if op == "think" else
                      "task_end" if op in {"transition", "stop", "STOP"} or event.get("rule") == "STOP" else None)
            if anchor:
                anchors[anchor][label + "_events"].append(event)
            else:
                unmatched_python[label].append(event)
    # Compare like-named observed motor boundaries, never sums of overlapping
    # intervals or fabricated high-level durations. Procedural/vision omissions
    # mean even these absolute-time deltas are diagnostic, not equivalence.
    phases = {"request": ("motor_preparation", "start_s"),
              "preparation_complete": ("motor_preparation", "end_s"),
              "initiation_complete": ("motor_initiation", "end_s"),
              "output": (None, "end_s"), "finish": (None, "end_s")}
    for name in ("point_parent", "open_parent_menu", "point_item", "click_item"):
        anchor = anchors[name]
        movements = [action for action in motor["actions"]
                     if action["action_id"] in anchor["reference_motor_action_ids"] and action["kind"] != "prepare_click"]
        anchor["motor_phase_timepoint_comparison"] = []
        if len(movements) != 1:
            anchor["motor_phase_comparison_status"] = "not_evaluated_missing_or_ambiguous_reference_action"
            continue
        action = movements[0]
        anchor["motor_phase_comparison_status"] = "diagnostic_absolute_times_no_origin_shift"
        for phase, (event_type, boundary) in phases.items():
            event_type = event_type or (("cursor_move" if action["kind"] == "cursor_move" else "click_output") if phase == "output" else
                                        ("cursor_finish" if action["kind"] == "cursor_move" else "click_finish"))
            ident = action["phase_events"].get(phase)
            reference = by_id.get(ident)
            candidates = [event for event in anchor["experimental_events"] if event.get("event_type") == event_type]
            counterpart = candidates[0] if len(candidates) == 1 else None
            experimental_time = counterpart.get(boundary) if counterpart else None
            baseline_time = None
            if len(anchor["baseline_events"]) == 1:
                if phase == "request":
                    baseline_time = anchor["baseline_events"][0].get("start_s")
                elif phase == "output" and action["kind"] == "cursor_move":
                    baseline_time = anchor["baseline_events"][0].get("end_s")
            reference_time = reference["timestamp_s"] if reference else None
            anchor["motor_phase_timepoint_comparison"].append({
                "phase": phase, "reference_event_id": ident, "reference_timestamp_s": reference_time,
                "experimental_event_id": counterpart.get("event_id") if counterpart else None,
                "experimental_event_type": event_type, "experimental_boundary": boundary,
                "experimental_timestamp_s": experimental_time, "baseline_timestamp_s": baseline_time,
                "experimental_minus_reference_s": experimental_time - reference_time if experimental_time is not None and reference_time is not None else None,
                "baseline_missing_boundary_policy": "null; baseline whole click block does not identify output/release; point end represents cursor output",
                "equivalence_evaluated": False})
    matched = {ident for anchor in anchors.values() for ident in anchor["reference_event_ids"]}
    return {"case_id": "NP-B1", "mapping_kind": "explicit case-specific many-to-one semantic anchors; not event equivalence",
            "time_origin_shift_s": 0, "anchors": list(anchors.values()), "reference_targets_from_saved_steps": targets,
            "unmatched_reference_events": [event for event in parsed["events"] if event["event_id"] not in matched],
            "unmatched_python_events": unmatched_python,
            "experimental_omissions": experimental.get("omissions", []) if experimental else None,
            "rule_binding": "archived NP-B1 named production identities; unexpected names stay unmatched",
            "no_claim_of_visual_completion_equivalence": True}


DIFFERENCE_COLUMNS = ("阶段/动作", "参考事件与行号", "Python事件", "输入一致性/unknown",
                      "起止或端点差值", "最早差异", "已确认原因", "待确认")


def difference_table(alignment):
    """A compact view derived only from parsed semantic-alignment evidence."""
    labels = {"point_parent": "指向菜单父目标", "open_parent_menu": "打开菜单（右键身份来自存档步骤）",
              "think": "Think", "point_item": "指向菜单项", "click_item": "点击菜单项", "task_end": "任务结束边界"}
    phase_labels = {"request": "请求", "output": "输出", "finish": "运动释放"}
    candidates = [(phase["reference_timestamp_s"], anchor["anchor"], phase["phase"])
                  for anchor in alignment["anchors"] for phase in anchor.get("motor_phase_timepoint_comparison", [])
                  if phase.get("experimental_minus_reference_s") not in (None, 0)]
    earliest = min(candidates) if candidates else None
    rows = []

    def stamp(value):
        return "unknown" if value is None else f"{value:.6f}"

    def event_name(event):
        return str(event.get("event_id", "index=" + str(event.get("index", "unknown")))) + ":" + str(event.get("event_type", event.get("op", "unknown")))

    for anchor in alignment["anchors"]:
        key = anchor["anchor"]
        reference = {event["event_id"]: event for event in anchor["reference_point_events"]}
        phases = [phase for phase in anchor.get("motor_phase_timepoint_comparison", []) if phase["phase"] in phase_labels]
        selected_ids = [phase["reference_event_id"] for phase in phases if phase["reference_event_id"] in reference]
        differences = []
        for phase in phases:
            baseline_time, reference_time = phase["baseline_timestamp_s"], phase["reference_timestamp_s"]
            baseline_delta = baseline_time - reference_time if baseline_time is not None and reference_time is not None else None
            differences.append(f"{phase_labels[phase['phase']]} 参考={stamp(reference_time)} / 基线={stamp(baseline_time)} (Δ={stamp(baseline_delta)}) / 实验={stamp(phase['experimental_timestamp_s'])} (Δ={stamp(phase['experimental_minus_reference_s'])}) s")
        if key == "think":
            pairs = anchor["reference_production_pairs"]
            matches = anchor["experimental_events"]
            if len(pairs) == 1:
                pair = pairs[0]
                selected_ids = [pair["selected_event_id"], pair["fired_event_id"]]
                if len(matches) == 1:
                    for endpoint, field in (("开始", "start_s"), ("结束", "end_s")):
                        first, second = pair[field], matches[0].get(field)
                        base = anchor["baseline_events"][0].get(field) if len(anchor["baseline_events"]) == 1 else None
                        differences.append(f"{endpoint} 参考={stamp(first)} / 基线={stamp(base)} (Δ={stamp(base-first if base is not None else None)}) / 实验={stamp(second)} (Δ={stamp(second-first if second is not None else None)}) s")
                else:
                    differences.append("实验Think端点 unknown；不代入0")
        if key == "task_end":
            selected_ids = list(reference)
            differences = ["参考 " + "；".join(f"{event['event_id']}={stamp(event['timestamp_s'])} s" for event in reference.values()),
                           "实验 " + "；".join(f"{event_name(event)}=[{stamp(event.get('start_s'))}, {stamp(event.get('end_s'))}] s" for event in anchor["experimental_events"]),
                           "STOP、队列耗尽与串行transition语义不同；不计算同义端点差值"]
        first_difference = ("最早可配对运动端点差异：" + phase_labels.get(earliest[2], earliest[2])
                            if earliest and earliest[1] == key else "更早差异已存在" if earliest else "unknown：没有可比较的非零运动端点差值")
        names = ", ".join(pair["production"] for pair in anchor["reference_production_pairs"])
        if key in {"point_parent", "point_item"}:
            confirmed = ("参考含 " + names if names else "参考产生式配对 unknown") + "；实验明确省略procedural及EMMA，运动请求直接从串行步骤发起"
            pending = "视觉门控、完整产生式/环境版本差异的独立贡献 unknown；不得用端点差额补偿参数"
        elif key in {"open_parent_menu", "click_item"}:
            has_early_prep = any(action["kind"] == "prepare_click" for action in anchor.get("reference_motor_actions", []))
            confirmed = ("参考有提前PUNCH准备记录" if has_early_prep else "参考提前PUNCH准备 unknown") + "；实验omissions明确不实现prepare-click lookahead，每步独立准备"
            pending = "完整原始点击/视觉/产生式协同 unknown；通用CLICK-MOUSE自身不提供左右键身份"
        elif key == "think":
            confirmed = "参考同名SELECTED/FIRED配对保留Think区间；Python保留Think块，开始时刻承接不同前序调度"
            pending = "前序差异的完整因果分解 unknown；Think端点差异不是Think参数误差"
        else:
            confirmed = "参考STOP产生式之后仍有运动事件；Python结束是最后串行步骤与运动队列完成"
            pending = "原版STOP、剩余视觉事件与新引擎终止条件是否等价 unknown"
        rows.append({"阶段/动作": labels[key],
            "参考事件与行号": "；".join(f"{ident}（第{reference[ident]['line_number']}行） {reference[ident]['message']}" for ident in selected_ids) or "unknown",
            "Python事件": "基线：" + (", ".join(event_name(event) for event in anchor["baseline_events"]) or "unknown") + "；实验：" + (", ".join(event_name(event) for event in anchor["experimental_events"]) or "unknown"),
            "输入一致性/unknown": "仅按保存步骤/目标作语义对应；完整输入、初始视觉态与版本一致性 unknown",
            "起止或端点差值": "；".join(differences) or "unknown：无同义端点，不推算相邻行耗时",
            "最早差异": first_difference,
            "已确认原因": confirmed, "待确认": pending})
    scope = alignment.get("reference_source_scope", {})
    rows.append({"阶段/动作": "来源与未对齐范围", "参考事件与行号": f"完整保留{len(alignment['unmatched_reference_events'])}条未匹配参考点事件；原文见point_events.json",
        "Python事件": "未实现项：" + ("；".join(alignment.get("experimental_omissions") or []) or "unknown"),
        "输入一致性/unknown": f"存档版本={scope.get('saved_version', {}).get('cogtool_version', 'unknown')}；2009源码提交={scope.get('source_2009_commit') or 'unknown'}；保存初始鼠标={scope.get('initial_mouse_position_saved') if scope.get('initial_mouse_position_saved') is not None else 'unknown'}",
        "起止或端点差值": "不复制总时间、不求重叠区间和、不平移时间轴；unknown不替换为0",
        "最早差异": "参考FIND等前置事件没有Python对应；上表仅定位最早可配对运动端点，不能宣称最早完整机制差异已确认",
        "已确认原因": "参考为历史缓存，实验为有限motor子集；保存时有效标志不能证明当前等价",
        "待确认": "原版同版本重跑、完整输入/视觉状态/参数与任务终止语义仍未对齐"})
    return rows


def write_difference_table(out, alignment):
    rows = difference_table(alignment)
    with (out / "differences.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=DIFFERENCE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    def escape(value):
        return str(value).replace("|", "\\|").replace("\n", "<br>")
    lines = ["# NP-B1 逐阶段差异", "", "本表直接取自 semantic_alignment.json。Δ 为相应 Python 端点时刻减参考端点时刻，单位秒；这是历史轨迹诊断，不是原版等价或准确性检验。基线整块点击没有输出/释放细分时刻，继续保留 unknown。", "",
             "| " + " | ".join(DIFFERENCE_COLUMNS) + " |", "| " + " | ".join(["---"] * len(DIFFERENCE_COLUMNS)) + " |"]
    lines.extend("| " + " | ".join(escape(row[column]) for column in DIFFERENCE_COLUMNS) + " |" for row in rows)
    (out / "DIFFERENCES_zh.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze(reference_trace, baseline_result, out, experimental_result=None, reference_metadata=None, reference_attributes=None):
    reference_trace, baseline_result, out = Path(reference_trace), Path(baseline_result), Path(out)
    if out.exists():
        raise TraceError("output already exists; use a fresh directory to preserve prior evidence")
    metadata_path = Path(reference_metadata) if reference_metadata else reference_trace.with_name("archived_reference.json")
    metadata = read(metadata_path) if metadata_path.is_file() else {}
    text = reference_trace.read_bytes().decode("utf-8")
    parsed = parse_trace(text)
    productions = pair_productions(parsed["events"])
    motor = link_motor(parsed["events"])
    baseline = read(baseline_result)
    experimental = read(experimental_result) if experimental_result else None
    checks = integrity(parsed, metadata)
    expected_hash = metadata.get("files", {}).get("archived_traceLines.txt", {}).get("sha256")
    hash_matches = sha(reference_trace) == expected_hash if expected_hash else None
    checks["checks"].append({"name": "metadata_trace_sha256", "status": "not_evaluated" if hash_matches is None else "consistent" if hash_matches else "inconsistent"})
    checks["has_inconsistency"] |= hash_matches is False
    alignment = semantic_alignment(parsed, productions, motor, metadata, baseline, experimental)
    attributes = read(reference_attributes) if reference_attributes else {}
    alignment["reference_source_scope"] = {
        "saved_version": metadata.get("saved_version", {}),
        "source_2009_commit": attributes.get("source_version_alignment", {}).get("source_2009_commit"),
        "initial_mouse_position_saved": attributes.get("initial_mouse_position_saved"),
        "staleness_assessment": attributes.get("staleness_assessment"),
        "original_rerun": False, "complete_input_equivalence": None}
    out.mkdir(parents=True)
    inputs = {"reference_trace": reference_trace, "baseline_result": baseline_result}
    if experimental_result:
        inputs["experimental_result"] = Path(experimental_result)
    if metadata_path.is_file():
        inputs["reference_metadata"] = metadata_path
    if reference_attributes:
        inputs["reference_attributes"] = Path(reference_attributes)
    evidence = {}
    for name, path in inputs.items():
        target = out / (name + path.suffix)
        shutil.copyfile(path, target)
        evidence[name] = {"source_path": str(path.resolve()), "copy": target.name, "sha256": sha(path)}
    write(out / "raw_lines.json", parsed["raw_lines"])
    write(out / "parameters.json", parsed["parameters"])
    write(out / "point_events.json", parsed["events"])
    write(out / "production_pairs.json", productions)
    write(out / "motor_actions.json", motor)
    write(out / "integrity.json", checks)
    write(out / "semantic_alignment.json", alignment)
    write_difference_table(out, alignment)
    with (out / "point_events.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["event_id", "line_number", "timestamp_s", "module", "message", "event_type", "duration_s"])
        writer.writeheader()
        writer.writerows({key: value for key, value in event.items() if key != "timestamp_text"} for event in parsed["events"])
    result = {"analysis_schema_version": 1, "case_id": "NP-B1", "reference_kind": "archived_reference", "original_rerun": False,
              "source_object_id": metadata.get("source_object_id"), "saved_version": metadata.get("saved_version"),
              "reference_attributes": read(reference_attributes) if reference_attributes else None,
              "reference_attributes_status": "separate_archive_source_audit" if reference_attributes else "not_provided_not_assumed_valid",
              "inputs": evidence, "raw_line_count": len(parsed["raw_lines"]), "point_event_count": len(parsed["events"]),
              "unknown_line_numbers": [row["line_number"] for row in parsed["raw_lines"] if row["kind"] == "unknown"],
              "parameter_count": len(parsed["parameters"]), "production_pair_count": len(productions["pairs"]),
              "integrity_has_inconsistency": checks["has_inconsistency"],
              "reference_total_s": metadata.get("cached_prediction_s"),
              "baseline_total_s": baseline.get("predicted_time_s"),
              "experimental_total_s": experimental.get("predicted_time_s") if experimental else None,
              "unknown_times_replaced_with_zero": False, "equivalence_evaluated": False,
              "runtime_s_mixed_with_model_time": False, "case_count": 1,
              "source_tool_sha256": sha(__file__)}
    write(out / "analysis.json", result)
    (out / "README_zh.md").write_text(
        "# NP-B1 历史轨迹分解\n\n此输出读取历史保存轨迹，没有重跑原 CogTool。原始逐行含未知内容完整保存在 raw_lines.json 和 reference_trace.txt。\n\n"
        "point_events 的 timestamp_s 是时刻，duration_s 均为 null；只有 production_pairs 中无歧义同名 SELECTED/FIRED 配对计算耗时。motor_actions 只对应请求、准备、启动、输出及结束，不以相邻行差值计费。\n\n"
        "semantic_alignment 是多对一语义定位，保留所有未匹配事件；没有平移时间轴，也没有把未实现视觉完成当零耗时。左右键身份来自保存步骤，通用 CLICK-MOUSE 日志本身不提供该身份。\n\n"
        "integrity 仅检验保存内容一致性。2e-7 秒阈值用于尾部浮点值与毫秒打印值的表示差异，不能解释为模型等价容差；任务 STOP 和运动完成分别报告。\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-trace", required=True, type=Path)
    parser.add_argument("--baseline-result", required=True, type=Path)
    parser.add_argument("--experimental-result", type=Path)
    parser.add_argument("--reference-metadata", type=Path)
    parser.add_argument("--reference-attributes", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = analyze(args.reference_trace, args.baseline_result, args.out, args.experimental_result, args.reference_metadata, args.reference_attributes)
    except (OSError, UnicodeError, json.JSONDecodeError, TraceError) as exc:
        print(f"trace analysis: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["integrity_has_inconsistency"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
