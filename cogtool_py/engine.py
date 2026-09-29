"""Offline serial baseline: no Java, Lisp, scheduler, or network backend.

Fitts components adapted from ACT-R/CogTool, LGPL-2.1-or-later.
Original copyright: CMU 2005–2013 and ACT-R authors (see NOTICE.md).
Python changes: 2026-09-24. Serial composition is a limited new baseline.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import time
from typing import Any

from . import ENGINE_VERSION, UPSTREAM, __version__, source
from .generator import _generate_validated
from .models import ModelError, ParameterSet, Project, Widget, fail
from .validation import validate_mouse, validate_parameters, validate_project, validate_widget


POINT_SOURCES = [
    source("lisp/actr6/core-modules/motor.lisp", "fitts:467-473;compute-exec-time(ply):612-615;move-cursor:752-761"),
    source("lisp/actr6/core-modules/vision.lisp", "approach-width:3175-3195"),
    source("lisp/actr6/framework/device-interface.lisp", "pixels-to-angle:263-264"),
    source("java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp", "frame-vis-loc-template:934-946"),
]


def point_time(mouse: tuple[float, float] | list[float], widget: Widget, parameters: ParameterSet) -> tuple[float, dict]:
    validate_mouse(mouse)
    validate_widget(widget)
    validate_parameters(parameters)
    dx, dy = widget.center[0] - mouse[0], widget.center[1] - mouse[1]
    distance = math.hypot(dx, dy)
    if distance == 0:
        return 0.0, {"distance_px": 0.0, "reason": "upstream move-cursor zero-distance no-op", "sources": POINT_SOURCES}
    # A central chord along the approach line, not min(width,height).
    width = min(widget.width * distance / abs(dx) if dx else math.inf,
                widget.height * distance / abs(dy) if dy else math.inf)
    scale = parameters.value("pixels_per_inch") * parameters.value("viewing_distance_in")
    if not all(math.isfinite(v) and v > 0 for v in (distance, width, scale)):
        fail("point geometry/parameters", "derived value is outside finite numeric range")
    d_angle = math.degrees(math.atan(distance / scale))
    w_angle = math.degrees(math.atan(width / scale))
    if not all(math.isfinite(v) and v > 0 for v in (d_angle, w_angle)):
        fail("point geometry/parameters", "derived value is outside finite numeric range")
    index = math.log2(d_angle / w_angle + 0.5)
    fitts = max(parameters.value("fitts_min_s"), parameters.value("fitts_coefficient_s") * index)
    total = parameters.value("motor_initiation_s") + fitts
    if not all(math.isfinite(v) for v in (index, fitts, total)) or total < 0:
        fail("point geometry/parameters", "computed time is out of range")
    return total, {"distance_px": distance, "approach_width_px": width,
                   "distance_deg": d_angle, "width_deg": w_angle, "fitts_index": index,
                   "fitts_s": fitts, "initiation_s": parameters.value("motor_initiation_s"),
                   "sources": POINT_SOURCES, "omits": "ACT-R preparation, production cycles, visual processing, overlap"}


@dataclass(frozen=True)
class PredictionResult:
    data: dict[str, Any]

    def __post_init__(self) -> None:
        # Distribution metadata is added after computation; no calculation or
        # input state is changed. Keep API and exported JSON representations equal.
        from .runtime import execution_identity
        object.__setattr__(self, "data", {**self.data, "distribution_identity": execution_identity(self.data)})

    def to_dict(self) -> dict[str, Any]:
        return self.data


def predict(project: Project, task_id: str | None = None) -> PredictionResult:
    from .io import implementation_fingerprint, input_hash

    started = time.perf_counter()
    validate_project(project)
    if task_id is not None and (not isinstance(task_id, str) or not task_id.strip()):
        fail("task", "task_id must be a nonempty string")
    if task_id is None and len(project.tasks) != 1:
        fail("task", "multiple tasks present; explicitly select --task")
    task = next((t for t in project.tasks if task_id is None or t.id == task_id), None)
    if task is None:
        fail("task", f"unknown task {task_id!r}")
    script = _generate_validated(project, task)
    if project.engine == "cogtool_control_prefix_experimental":
        from .control_prefix import predict_control_prefix
        return PredictionResult(predict_control_prefix(project, task, script, started))
    if project.engine != "klm_baseline":
        # No fallback: the opt-in engine has a separately versioned, strict scope.
        from .motor_subset import predict_motor_subset
        return PredictionResult(predict_motor_subset(project, task, script, started))
    events = []
    total = 0.0
    resources = {"point": "motor", "click": "motor", "right_click": "motor", "key": "motor", "home": "motor",
                 "think": "cognitive", "look_at": "visual", "wait": "system", "transition": "system"}
    for step in script.steps:
        details: dict[str, Any] = {}
        if step.duration_s is not None:
            duration = step.duration_s
            details["duration_source"] = "explicit demonstration/transition or generated Think (see step and parameters)"
        elif step.op == "point":
            widget = project.design.frame(step.frame, "engine").widget(step.target, "engine")
            try:
                duration, details = point_time(step.state_before["mouse"], widget, project.parameters)
            except (ValueError, OverflowError, ZeroDivisionError) as exc:
                fail(f"task[{task.id}].steps[{step.demo_index}].point", str(exc))
        else:
            parameter_name = {"click": "click_s", "right_click": "click_s", "key": "key_s", "home": "homing_s"}[step.op]
            duration = project.parameters.value(parameter_name)
            details["parameter"] = parameter_name
        if duration < 0 or not math.isfinite(duration) or not math.isfinite(total + duration):
            fail(f"task[{task.id}].steps[{step.demo_index}]", "computed time is out of range")
        events.append({"index": len(events), "step_index": step.index, "demo_index": step.demo_index,
                       "op": step.op, "origin": step.origin, "resource": resources[step.op],
                       "start_s": total, "end_s": total + duration, "duration_s": duration, "details": details})
        total += duration
    model_hash = input_hash(project)
    implementation = implementation_fingerprint()
    execution_fingerprint = hashlib.sha256(json.dumps({
        "implementation_sha256": implementation["sha256"], "input_sha256": model_hash,
        "task_id": task.id, "engine_version": ENGINE_VERSION,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    data = {
        "result_schema_version": 1, "software": "CogTool-Py", "software_version": __version__,
        "engine": {"name": project.engine, "version": ENGINE_VERSION}, "upstream": UPSTREAM,
        "project_id": project.id, "task_id": task.id, "input_sha256": model_hash,
        "implementation": implementation, "execution_fingerprint": execution_fingerprint,
        "parameters": project.parameters.result_dict(), "predicted_time_s": total,
        "program_runtime_s": time.perf_counter() - started, "time_unit": "s",
        "initial_state": asdict(task.demonstration.initial), "final_state": script.final_state,
        "demonstration": [s.to_dict() for s in task.demonstration.steps],
        "steps": [asdict(s) for s in script.steps], "events": events,
        "timing_boundary": "start before first generated operator at t=0; end after final operator and any response barrier",
        "validation": {"original_comparison": "unverified", "differential_tests": "not_executed",
                       "claim": "serial baseline, not a CogTool/ACT-R compatible predictor"},
        "scope": ["known targets, rectangular button/link/textbox, specified task path",
                  "at most one initially closed single-level context menu selection per task; known item only; no general menu state or ACT-R equivalence",
                  "US unshifted physical keystrokes; mouse hand tracked, other hand remains on keyboard",
                  "serial scheduling only; resource labels do not imply overlapping modules"],
        "warnings": ["klm_baseline: no ACT-R production, preparation, resource overlap or EMMA; total is not an original CogTool prediction",
                     "click_s, key_s and homing_s are explicit modeler assumptions, not upstream total-time defaults",
                     "visual dwell and system wait are explicit serial blocks; keyboard application behavior is not simulated",
                     *script.warnings],
    }
    return PredictionResult(data)
