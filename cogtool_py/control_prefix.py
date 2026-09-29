"""Bounded 2014 CogTool rule control up to the first mouse request.

Adapted from CMU CogTool / ACT-R sources, LGPL-2.1-or-later; see NOTICE.md.
Python changes 2026-09-26. Does not implement EMMA completion, subsequent script
commands or STOP. A drained queue never constitutes a complete task prediction.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import time

from . import UPSTREAM, __version__, source
from .models import CONTROL_ENGINE
from .motor_subset import Clock, MotorModule, milliseconds

VERSION = "0.1.0"
JAVA = "java/edu/cmu/cs/hcii/cogtool/model/ACTRPredictionAlgo.java"
VISION = "lisp/actr6/core-modules/vision.lisp"
SOURCES = {
    "start": source(JAVA, "startScript:1741-1783"),
    "look": source(JAVA, "generateLookAt:2513-2584"),
    "move": source(JAVA, "visit(ActionScriptStep):2075-2117"),
    "selection": source("lisp/actr6/core-modules/procedural.lisp", "conflict-resolution:1330-1451;production-selected:1875-1887"),
    "firing": source("lisp/actr6/core-modules/procedural.lisp", "production-fired:1894-1925"),
    "binding": source("lisp/actr6/support/production-parsing-support.lisp", "buffer binding:206-226;action variable substitution:802-807"),
    "requested": source("lisp/actr6/framework/buffers.lisp", "requested/unrequested query:644-650"),
    "stuffing": source(VISION, "stuff-visloc-buffer:891-910;reset:2646;find-location:2773-2795"),
    "lock": source(VISION, "warn-vision:2691-2696;pm-module-request:2701-2708"),
    "initialization": source("java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp",
                             "build-vis-locs-for:891-928;transition:1037-1049;cogtool-run-model:1137-1164"),
    "priority": source("lisp/actr6/framework/scheduling.lisp", "compare-events:823-860;schedule-event-relative:967-968"),
    "manual_queue": source("lisp/actr6/support/general-pm.lisp", "check-jam:304-311;maybe-execute-movement:532-537") + "; " + source("java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp", "prepare-movement:55-69;preparation-complete:101-111;finish-movement:172-176"),
}
POLICY = {
    "source_commit": UPSTREAM["commit"], "trace_enabled": True, "use_tree": False,
    "esc": True, "er": False, "egs": 0, "iu": 0, "ul": False, "ut": None,
    "vpft": False, "ppm": False, "hooks": None, "runtime_kludge_loaded": False,
    "emit_virtual_frames": False, "use_emma": True, "auto_attend_slot": False,
    "vstu": "not_defined_by_selected_source",
    "selection": "highest utility; ER=nil and use-tree=nil: last defined wins an equal-utility tie",
    "selected_rule_state_changes": "no cancellation/re-matching; firing uses selection-time chunk bindings",
    "scope": "static scene until first request; external changes are explicitly synthetic controller tests",
}


class PrefixController:
    def __init__(self, project, task, script):
        self.project, self.task, self.script = project, task, script
        self.config = project.control
        self.clock = Clock()
        self.motor = MotorModule(project, task, self.clock)
        self.events, self.snapshots = [], []
        self.conflict_pending = False
        self.selected = None
        self.first_mouse_request = None
        self.failure = None
        self.event_count = 0
        self.step = script.steps[0] if script.steps else None
        self.frame = project.design.frame(task.demonstration.initial.frame, "control.initial")
        self.target = self.step.target if self.step and self.step.op == "point" else None
        self.locations = {}
        for w in self.frame.widgets:
            self.locations[w.id] = {"chunk_id": f"location:{self.frame.id}:{w.id}",
                                    "target": w.id, "value": w.name + " in " + self.frame.name,
                                    "x": w.center[0], "y": w.center[1], "kind": "widget",
                                    "creation_time_s": 0.0}
        for a in self.config.auxiliary_locations:
            if a.frame == self.frame.id:
                self.locations[a.id] = {"chunk_id": f"location:{a.frame}:{a.id}",
                                       "target": a.id, "value": a.id, "x": a.x, "y": a.y,
                                       "kind": "group", "creation_time_s": 0.0}
        normal = self.config.profile == "source_2014_defaults"
        self.initial_scene_targets = set(self.locations if self.config.visible_targets is None else self.config.visible_targets)
        self.visible = set() if normal else set(self.initial_scene_targets)
        self.state = {
            "current_target": self.target, "current_frame": None if normal else self.frame.id,
            "frame_visible": False if normal else self.config.frame_visible,
            "goal_state": "start" if normal else "look_initial", "suppress_re_encoding": False,
            "visual_location": self.location(self.config.visual_location),
            "location_requested": self.config.location_requested, "location_failure": False,
            "visual_content": self.config.visual_content,
            "visual_preparation": self.config.visual_preparation,
            "visual_processor": self.config.visual_processor,
            "visual_execution": self.config.visual_execution,
            "visual_completion_time_s": None, "visual_completion_unmodeled": False,
            "visual_last_confirmed_at_s": 0.0,
            "device_locked": False, "procedural_busy": False, "selected_rule": None,
            "scene_locations": sorted(self.visible),
            "menu_open": False,
            "menu_visibility_policy": "2014 emitVirtualFrames=false exports current-frame items even when menu is closed",
        }
        # Freeze each rule's effective :at for this immutable parameter profile.
        self.action_time = project.parameters.value("production_action_s")

    def location(self, target):
        return deepcopy(self.locations.get(target)) if target is not None else None

    def snapshot(self):
        return {**deepcopy(self.state), "manual": deepcopy(self.motor.state),
                "manual_state": self.motor.manual_state, "time_s": self.clock.now / 1000}

    def record(self, kind, *, rule=None, details=None, origin="source_rule", source_key=None):
        event = {"index": len(self.events), "event_id": f"control-{len(self.events)}",
                 "event_type": kind, "op": kind, "rule": rule, "origin": origin,
                 "demo_index": self.step.demo_index if self.step else None,
                 "step_index": self.step.index if self.step else None,
                 "target": self.target, "resource": "procedural" if "production" in kind else "control",
                 "start_s": self.clock.now / 1000, "end_s": self.clock.now / 1000,
                 "duration_s": 0.0, "details": details or {}, "state_after": self.snapshot(),
                 "source": SOURCES.get(source_key) if source_key else None}
        self.events.append(event)
        return event

    def changed(self, kind, updates, source_key, *, details=None, origin="source_rule"):
        before = self.snapshot()
        self.state.update(deepcopy(updates))
        event = self.record(kind, details=details, origin=origin, source_key=source_key)
        event["state_before"] = before
        self.check_later()
        return event

    def check_later(self):
        if not self.conflict_pending and not self.control_finished() and self.failure is None:
            self.conflict_pending = True
            self.clock.schedule(0, self.conflict, priority=":min")

    def control_finished(self):
        return self.first_mouse_request is not None

    def before_selection(self, chosen):
        """Extended task scope binds step context without changing prefix rules."""

    def frame_matches(self):
        return self.state["current_frame"] == self.frame.id and self.state["frame_visible"]

    def visual_free(self):
        return all(self.state[k] == "free" for k in
                   ("visual_preparation", "visual_processor", "visual_execution"))

    def candidates(self):
        """Template guards, not a prescribed sequence. No requested/visibility guard added."""
        goal, loc = self.state["goal_state"], self.state["visual_location"]
        same = bool(loc and self.target in self.locations and
                    loc["value"] == self.locations[self.target]["value"])
        candidates = []
        if self.state["suppress_re_encoding"] and self.visual_free() and self.frame_matches():
            candidates.append({"name": "*suppress-re-encoding", "utility": 0, "order": 0, "at_s": 0})
        if goal == "start":
            candidates.append({"name": "set-start-frame", "utility": 0, "order": 1, "at_s": 0})
        if self.frame_matches():
            if goal == "look_initial":
                candidates.append({"name": "find", "utility": -1, "order": 2, "at_s": self.action_time})
            if goal in {"look_initial", "look_after_find"} and same and self.visual_free():
                candidates.append({"name": "look-at", "branch": "direct" if goal == "look_initial" else "after_find",
                                   "utility": 0, "order": 3 if goal == "look_initial" else 4, "at_s": self.action_time})
            if goal == "move":
                candidates.append({"name": "find-location", "utility": -1, "order": 5, "at_s": self.action_time})
                if same and self.motor.manual_state == "free":
                    candidates.append({"name": "move-mouse", "utility": 0, "order": 6, "at_s": self.action_time})
        return candidates

    def conflict(self):
        self.conflict_pending = False
        if self.state["procedural_busy"] or self.control_finished() or self.failure:
            return
        candidates = self.candidates()
        chosen = max(candidates, key=lambda c: (c["utility"], c["order"])) if candidates else None
        self.record("conflict_resolution", details={"candidates": candidates, "selected": chosen,
                    "policy": POLICY["selection"]}, source_key="selection")
        if chosen is None:
            return
        self.before_selection(chosen)
        # Bind the location chunk identity now. Replacing a buffer later does not
        # change that binding; no synthetic operation mutates an existing chunk.
        self.selected = {**chosen, "bound_location": deepcopy(self.state["visual_location"]),
                         "selected_at_s": self.clock.now / 1000}
        if chosen["name"] == "look-at":
            self.state["device_locked"] = True
            self.record("device_lock", rule="look-at", source_key="lock")
        selected = deepcopy(self.selected)
        self.clock.schedule(0, lambda: self.select(selected), priority=":max")

    def select(self, selected):
        self.state.update(procedural_busy=True, selected_rule=deepcopy(selected))
        self.record("production_selected", rule=selected["name"],
                    details={**deepcopy(selected), "event_priority": ":max", "scheduled_firing_time_s":
                             (self.clock.now + milliseconds(selected["at_s"])) / 1000},
                    source_key="selection")
        self.clock.schedule(selected["at_s"], lambda: self.fire(selected), priority=0)

    def goal_update(self, **updates):
        self.clock.schedule(0, lambda: self.changed("goal_update", updates, "firing"), priority=100)

    def display(self):
        self.state["current_frame"] = self.frame.id
        self.state["frame_visible"] = True
        self.visible = set(self.initial_scene_targets)
        self.state["scene_locations"] = sorted(self.visible)
        self.record("proc_display", details={"locations": list(self.locations.values()),
                    "closed_menu_items_exported": True}, source_key="initialization")
        if self.config.auto_stuffing:
            self.stuff()

    def stuff(self):
        if self.state["visual_location"] is not None or self.state["device_locked"] or not self.frame_matches():
            return
        candidates = [self.locations[k] for k in self.visible]
        if not candidates:
            return
        left = min(c["x"] for c in candidates)
        newest = max(c["creation_time_s"] for c in candidates if c["x"] == left)
        eligible = [c for c in candidates if c["x"] == left and c["creation_time_s"] == newest]
        if len(eligible) != 1:
            self.failure = "unsupported"
            self.record("unsupported_stuffing_tie", details={"candidates": eligible,
                        "missing": "ACT-R random choice and chunk-name ordering; no arbitrary winner chosen"})
            return
        self.clock.schedule(0, lambda: self.changed("visual_location_stuffed",
                            {"visual_location": deepcopy(eligible[0]), "location_requested": False,
                             "location_failure": False}, "stuffing",
                            details={"selection": "screen-x lowest, new; unique newest candidate",
                                     "event_priority": 10}), priority=10)
        self.state["device_locked"] = True
        self.record("stuffing_device_lock", source_key="stuffing")
        self.clock.schedule(0, lambda: self.changed("display_unlock", {"device_locked": False}, "stuffing"), priority=9)

    def location_search_available(self):
        return self.target in self.visible and self.frame_matches()

    def find_request(self):
        self.record("visual_location_request", details={"value": self.locations[self.target]["value"]},
                    source_key="look")
        self.clock.schedule(0, lambda: self.changed("visual_location_clear",
                            {"visual_location": None, "location_requested": False}, "requested"), priority=10)

        def locate():
            found = self.location(self.target) if self.location_search_available() else None
            if found is None:
                # The search callback sets failure at priority 0. There is no
                # priority-10 buffer write on failure (vision:2447-2449).
                self.changed("visual_location_failure", {"location_failure": True}, "stuffing",
                             details={"success": False, "event_priority": 0})
                self.clock.schedule(0, lambda: self.record("find_loc_failure", source_key="stuffing",
                                    details={"event_priority": 0, "effect": "trace-only failure notification"}), priority=0)
                return
            self.clock.schedule(0, lambda: self.changed("visual_location_return",
                                {"visual_location": found, "location_requested": True,
                                 "location_failure": False}, "stuffing",
                                details={"success": True, "event_priority": 10}), priority=10)
            if found is not None:
                self.state["device_locked"] = True
                self.record("lookup_device_lock", source_key="stuffing")
                self.clock.schedule(0, lambda: self.changed("lookup_device_unlock", {"device_locked": False},
                                    "stuffing"), priority=9)
        self.clock.schedule(0, locate, priority=0)

    def attention_request(self, bound):
        self.record("visual_attention_request", details={"bound_location": bound,
                    "completion_s": None, "status": "EMMA completion unimplemented"}, source_key="look")
        self.clock.schedule(0, lambda: self.changed("visual_buffer_clear", {"visual_content": None}, "look"), priority=10)

        def begin():
            if bound is None or bound["target"] not in self.visible:
                self.failure = "unsupported"
                self.record("unsupported_attention_to_stale_location", details={"bound_location": bound,
                            "reason": "preserved rule firing; stale-object EMMA behavior outside prefix"})
                return
            self.changed("visual_attention_started", {"visual_processor": "busy",
                         "visual_completion_unmodeled": True, "visual_last_confirmed_at_s": self.clock.now / 1000},
                         "look", details={"state_status": "last confirmed at request; future EMMA completion unknown"})
        self.clock.schedule(0, begin, priority=0)
        self.clock.schedule(0, lambda: self.changed("visual_request_unlock", {"device_locked": False}, "lock"), priority=":min")

    def fire(self, selected):
        # The locked version explicitly says selected productions cannot fail
        # to fire; do not re-evaluate guards after a synthetic buffer update.
        name = selected["name"]
        self.record("production_fired", rule=name, details={"selection": selected,
                    "lhs_rechecked": False}, source_key="firing")
        if name == "set-start-frame":
            self.display()
            self.goal_update(goal_state="look_initial")
        elif name in {"find", "find-location"}:
            if name == "find":
                self.goal_update(goal_state="look_after_find")
            self.clock.schedule(0, self.find_request, priority=50)
        elif name == "look-at":
            self.goal_update(goal_state="move", suppress_re_encoding=True)
            bound = deepcopy(selected["bound_location"])
            self.clock.schedule(0, lambda: self.attention_request(bound), priority=50)
        elif name == "*suppress-re-encoding":
            self.goal_update(suppress_re_encoding=False)
            self.clock.schedule(0, lambda: self.changed("visual_clear_request",
                                {"visual_content": None}, "start"), priority=50)
        elif name == "move-mouse":
            self.goal_update(goal_state="after_first_mouse_request")
            bound = deepcopy(selected["bound_location"])
            self.clock.schedule(0, lambda: self.mouse_request(bound), priority=50)
        self.state.update(procedural_busy=False, selected_rule=None)
        self.selected = None
        self.check_later()

    def mouse_request(self, bound):
        if bound is None or bound["target"] != self.target:
            self.failure = "unsupported"
            self.record("unsupported_bound_mouse_target", details={"bound_location": bound})
            return
        if self.first_mouse_request is not None:
            raise RuntimeError("control invariant: duplicate first mouse request")
        self.first_mouse_request = self.clock.now / 1000
        event = self.record("mouse_request", rule="move-mouse", details={"bound_location": bound}, source_key="move")
        if self.motor.manual_state != "free":
            # A selected production still fires. Upstream preparation can jam,
            # or execution can queue, if manual state changed meanwhile. Those
            # mechanisms are not part of this first-request/free-manual scope.
            self.failure = "unsupported"
            self.record("unsupported_manual_queue", rule="move-mouse", source_key="manual_queue",
                        details={"reason": "manual changed after selection; jam/execution-queue behavior outside prefix",
                                 "request_preserved": True, "motor_output_not_synthesized": True})
            return

        def observe(module, change):
            self.record("manual_state_update", details={"motor_change": change}, source_key="move")
            self.check_later()
        # No translated trace and no time shift: this is the shared module's
        # actual asynchronous request at the production's module-request time.
        self.motor.request(self.step, dependencies=(event["event_id"],), on_state_change=observe)

    def synthetic_update(self, event):
        details = {"update": asdict(event), "scope": "controller-only test, not visual-module validation"}
        changes = {}
        if event.kind == "location_set":
            changes = {"visual_location": self.location(event.target), "location_requested": event.requested,
                       "location_failure": False}
        elif event.kind == "location_clear":
            changes = {"visual_location": None, "location_requested": False}
        elif event.kind in {"visual_free", "visual_busy"}:
            changes = {"visual_processor": "free" if event.kind == "visual_free" else "busy"}
            if event.kind == "visual_free":
                changes.update(visual_preparation="free", visual_execution="free", visual_content=event.target,
                               visual_completion_time_s=self.clock.now / 1000, visual_completion_unmodeled=False)
        elif event.kind in {"frame_hide", "frame_show"}:
            changes = {"frame_visible": event.kind == "frame_show"}
        elif event.kind in {"manual_busy", "manual_free"}:
            self.motor.state["motor_execution"] = "busy" if event.kind == "manual_busy" else "free"
        elif event.kind in {"scene_add", "scene_remove"}:
            if event.kind == "scene_add":
                self.visible.add(event.target)
            else:
                self.visible.discard(event.target)
            changes = {"scene_locations": sorted(self.visible)}
        self.changed("synthetic_state_update", changes, "priority", details=details,
                     origin="synthetic_controller_only")

    def run(self):
        if self.target is None:
            self.failure = "unsupported"
            self.record("unsupported_prefix", details={"reason": "prefix requires first generated step point; preceding Think/Home/etc not silently skipped"})
        elif len({v["value"] for v in self.locations.values()}) != len(self.locations):
            self.failure = "unsupported"
            self.record("unsupported_duplicate_visual_values", details={"reason": "ambiguous upstream value mapping"})
        else:
            self.record("initial_state", details={"profile": self.config.profile, "provenance": self.config.provenance},
                        source_key="initialization")
            for event in self.config.updates:
                priority = 10 if event.kind in {"location_set", "location_clear"} else 0
                self.clock.schedule(event.at_s, lambda e=event: self.synthetic_update(e), priority=priority)
            if self.config.profile != "source_2014_defaults" and self.config.auto_stuffing:
                self.clock.schedule(0, self.stuff, priority=10)
            self.check_later()
        self.drain_bounded()
        if self.failure:
            status = self.failure
        elif self.first_mouse_request is not None:
            status = "partial"
        elif (not self.visual_free() or self.motor.manual_state != "free" or
              self.state["visual_completion_unmodeled"]):
            status = "waiting"
        else:
            status = "deadlock"
        self.record("prefix_boundary", details={"completion_status": status,
                    "queue_empty": not self.clock.queue, "full_task_completed": False,
                    "pending_events": len(self.clock.queue),
                    "visual_state_interpretation": "last confirmed partial-model state; unmodeled completion is not asserted absent"})
        return status

    def drain_bounded(self):
        while self.clock.queue and self.failure is None:
            if self.event_count >= self.config.max_events:
                self.failure = "event_limit"
                break
            if self.clock.queue[0][0] > milliseconds(self.config.max_time_s):
                self.failure = "time_limit"
                if self.config.run_policy == "reference_2014":
                    # run:539-551 advances simulated time to its fixed bound;
                    # no pending movement/visual callback is executed early.
                    self.clock.now = milliseconds(self.config.max_time_s)
                break
            self.clock.step()
            self.event_count += 1
        # Source run executes all equal-time calls, then reports the time-limit
        # boundary even if the final callback emptied the queue (532-557).
        if (self.failure is None and self.config.run_policy == "reference_2014" and
                self.clock.now >= milliseconds(self.config.max_time_s)):
            self.failure = "time_limit"


def predict_control_prefix(project, task, script, started):
    from .io import implementation_fingerprint, input_hash

    integrated = project.control.execution_scope == "integrated_task"
    if integrated:
        from .task_control import IntegratedController
        controller = IntegratedController(project, task, script)
    else:
        controller = PrefixController(project, task, script)
    version = "0.6.0" if integrated else VERSION
    status = controller.run()
    model_hash, implementation = input_hash(project), implementation_fingerprint()
    fingerprint = hashlib.sha256(json.dumps({"input_sha256": model_hash, "implementation_sha256": implementation["sha256"],
                                            "engine_version": version, "task_id": task.id},
                                           sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    selected = [e for e in controller.events if e["event_type"] == "production_selected"]
    fired = [e for e in controller.events if e["event_type"] == "production_fired"]
    target_selected = [e for e in selected if e["rule"] != "set-start-frame"]
    target_fired = [e for e in fired if e["rule"] != "set-start-frame"]
    outputs = [e["end_s"] for e in controller.motor.events if e["event_type"] in {"cursor_move", "click_output", "key_output", "hand_move", "hand_noop"} and e["state_after"] is not None]
    releases = [e["end_s"] for e in controller.motor.events if e["event_type"] in {"cursor_finish", "click_finish", "key_finish", "hand_finish"} and e["state_after"] is not None]
    remaining = ["EMMA encoding/saccade completion", "subsequent generated steps and production rules",
                 "prepare-click lookahead", "full task STOP and queue termination equivalence"]
    result = {
        "result_schema_version": 1, "software": "CogTool-Py", "software_version": __version__,
        "engine": {"name": CONTROL_ENGINE, "version": version}, "engine_id": CONTROL_ENGINE,
        "engine_version": version, "source_commit": UPSTREAM["commit"], "upstream": UPSTREAM,
        "project_id": project.id, "task_id": task.id,
        "input_sha256": model_hash, "parameters": project.parameters.result_dict(),
        "implementation": implementation, "execution_fingerprint": fingerprint,
        "initial_state_profile": project.control.profile, "initial_state_provenance": project.control.provenance,
        "control_configuration": project.control.to_dict(), "runtime_policy": POLICY,
        "first_selected_rule": selected[0]["rule"] if selected else None,
        "first_firing_time_s": fired[0]["start_s"] if fired else None,
        "first_target_rule": target_selected[0]["rule"] if target_selected else None,
        "first_target_rule_firing_time_s": target_fired[0]["start_s"] if target_fired else None,
        "first_mouse_request_time_s": controller.first_mouse_request,
        "task_stop_time_s": None, "last_device_output_time_s": max(outputs) if outputs else None,
        "last_manual_release_time_s": max(releases) if releases else None,
        "reported_task_time_s": None, "predicted_time_s": None, "completion_status": status,
        "remaining_unsupported_mechanisms": remaining, "original_rerun_s": None,
        "program_runtime_s": time.perf_counter() - started, "time_unit": "s",
        "initial_state": asdict(task.demonstration.initial), "final_state": controller.snapshot(),
        "demonstration": [step.to_dict() for step in task.demonstration.steps],
        "steps": [asdict(step) for step in script.steps], "events": controller.events,
        "motor_events": controller.motor.events, "motor_state_changes": controller.motor.state_changes,
        "processed_event_count": controller.event_count,
        "timing_boundary": "rule initialization through first mouse request and its observable motor completion; no full-task STOP/EMMA completion",
        "validation": {"original_comparison": "unverified", "claim": "bounded rule prefix, not a complete task prediction"},
        "scope": ["fixed 2014 trace-enabled deterministic default policy", "first generated point only; remaining commands retained but unexecuted",
                  "source-defined scene profile or explicitly synthetic controller initial state", "reuse shared MotorModule without shifted traces"],
        "warnings": ["No complete task time is reported.", "2009 initial state and source equivalence remain unknown.",
                     "Visual content, visual-location content and module state are distinct.",
                     "Source policy provenance does not imply an actual 2014 original run."],
    }
    if integrated:
        result.update(controller.result_fields(status))
    return result
