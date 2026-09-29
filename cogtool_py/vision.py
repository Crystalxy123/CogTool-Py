"""Pinned CogTool EMMA lifecycle for static, string-valued visual objects.

Adapted from CMU CogTool / ACT-R sources, LGPL-2.1-or-later; see NOTICE.md.
Python changes 2026-09-26. This module shares the controller's Clock, never
drains it, and does not equate encoding completion with eye movement completion.
Dynamic scene replacement and overlapping attention requests are explicit
subset boundaries; boundary cleanup is not claimed as upstream cancellation.
"""
from copy import deepcopy
import math

from . import source
from .models import VISION_DEFAULTS, finite_coordinate, fail
from .motor_subset import Clock, milliseconds

EMMA = "java/edu/cmu/cs/hcii/cogtool/resources/emma.lisp"
COGTOOL = "java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp"
PM = "lisp/actr6/support/general-pm.lisp"
VISION = "lisp/actr6/core-modules/vision.lisp"
SOURCES = {
    "request": source(EMMA, "move-attention:257-310"),
    "encoding": source(EMMA, "recog-time:504-509;object-frequency:526-536") + "; " + source(COGTOOL, "encoding-complete:133-149;default-global-parameters:1118-1125"),
    "preparation": source(EMMA, "build-sacc-mvmt:543-552;feat-differences:223-227;initiate-eye-move:395-416") + "; " + source(PM, "compute-prep-time:650-655;num-to-prepare:752-757") + "; " + source(COGTOOL, "preparation-complete replacement:96-111"),
    "execution": source(EMMA, "compute-exec-time:203-215;perform-movement:473-485;complete-eye-move:443-462"),
    "geometry": source("lisp/actr6/framework/device-interface.lisp", "angle-to-pixels:255-257;pixels-to-angle:263-264") + "; " + source("lisp/actr6/framework/misc-utils.lisp", "polar-move-xy:631-641"),
    "buffer": source(VISION, "attend-to-object:1360-1377"),
    "clear": source(PM, "clear:284-292;check-jam:304-311;attn-module clear:839-849") + "; " + source(EMMA, "clear:369-370") + "; " + source(VISION, "clear:2398-2408;remove-tracking:2348-2353"),
    "finish": source(COGTOOL, "finish-movement:167-175") + "; " + source(PM, "maybe-execute-movement:535-537"),
    "initial": source(EMMA, "reset-emma-module:775-783"),
    "noise": source(COGTOOL, "add-gaussian-noise override:1096-1104") + "; " + source("lisp/actr6/framework/random.lisp", "randomize-time default:382-387;randomize-time:435-450"),
}


class VisionModule:
    """Nonblocking EMMA resources, encoding and saccades on an injected clock.

    ``visible`` must report membership of the bound location's canonical scene
    object, not menu activation. Ordinary CogTool emitVirtualFrames=false has
    closed-menu items in the visicon. Buffer clearing from production syntax
    belongs to the controller; ``clear`` models the visual module command.
    """
    def __init__(self, parameters, clock=None, *, visible=lambda target: True,
                 on_state_change=None, initial_eye=(0, 0), location_present=None):
        parameters.validate()
        if not VISION_DEFAULTS.keys() <= parameters.entries.keys():
            fail("vision.parameters", "all effective vision parameters are required")
        if not isinstance(initial_eye, (tuple, list)) or len(initial_eye) != 2:
            fail("vision.initial_eye", "expected two finite coordinates")
        eye = [finite_coordinate(v, f"vision.initial_eye[{i}]") for i, v in enumerate(initial_eye)]
        self.parameters = parameters
        self.clock = clock if clock is not None else Clock()
        self.visible, self.on_state_change = visible, on_state_change
        self._present = location_present or (lambda loc: self.visible(loc["target"]))
        self.events, self.state_changes, self.requests = [], [], []
        self.unsupported_reason = None
        self.state = {
            "visual_preparation": "free", "visual_processor": "free", "visual_execution": "free",
            "visual_content": None, "visual_object": None, "visual_requested": False,
            "visual_completion_time_s": None, "visual_completion_unmodeled": False,
            "eye_location": eye, "next_eye_location": None, "moving_attention": None,
            "attended_target": None, "attention_failure": False, "last_prepared": None,
            "pending_events": [], "unsupported_reason": None,
        }
        self._scheduled = []
        self._last_prepared = None
        self._execution_queue = []
        self._shift_start_s = 0.0
        self._shift_duration_s = None
        self._location = None

    @property
    def visual_state(self):
        return "busy" if any(self.state[k] == "busy" for k in
                             ("visual_preparation", "visual_processor", "visual_execution")) else "free"

    @property
    def has_pending_events(self):
        return any(not handle.cancelled and not handle.executed for handle, _ in self._scheduled)

    def _sync_pending(self):
        self.state["pending_events"] = [event["event_id"] for handle, event in self._scheduled
                                        if not handle.cancelled and not handle.executed]
        for request in self.requests:
            pending = any(event["request_id"] == request["request_id"] and
                          not handle.cancelled and not handle.executed
                          for handle, event in self._scheduled)
            request["completed"] = bool(request["encoding_completed"] and not pending and
                                         request["unsupported_reason"] is None)

    def _change(self, changes, trigger, event):
        before = deepcopy(self.state)
        self.state.update(deepcopy(changes))
        self._sync_pending()
        record = {"index": len(self.state_changes), "time_s": self.clock.now / 1000,
                  "trigger": trigger, "event_id": event["event_id"],
                  "request_id": event["request_id"], "before": before, "after": deepcopy(self.state),
                  "source": event["source"]}
        self.state_changes.append(record)
        if self.on_state_change is not None:
            self.on_state_change(self, record)

    def _event(self, kind, request, *, details=None, dependencies=(), priority=0):
        event = {"index": len(self.events), "event_id": f"vision-{len(self.events)}",
                 "request_id": request["request_id"] if request else None,
                 "event_type": kind, "op": kind, "target": request["location"]["target"] if request else None,
                 "resource": "vision", "start_s": self.clock.now / 1000,
                 "end_s": self.clock.now / 1000, "duration_s": 0.0,
                 "event_priority": priority, "dependencies": list(dependencies), "status": "executed",
                 "source": [], "details": details or {}, "state_before": deepcopy(self.state),
                 "state_after": None}
        self.events.append(event)
        if request:
            request["event_ids"].append(event["event_id"])
        return event

    def _schedule(self, kind, delay_s, callback, request, sources, *, details=None, dependencies=(), priority=0):
        # Validate the exact unrounded delay before creating a partial event.
        milliseconds(delay_s)
        event = self._event(kind, request, details=details, dependencies=dependencies, priority=priority)
        event.update(status="pending", source=list(sources))

        def execute():
            event["status"] = "executed"
            event["state_before"] = deepcopy(self.state)
            callback(event)
            self._sync_pending()
            event["state_after"] = deepcopy(self.state)

        handle = self.clock.schedule_event(delay_s, execute, priority=priority)
        event["end_s"] = handle.when_ms / 1000
        event["duration_s"] = event["end_s"] - event["start_s"]
        event["schedule_order"] = handle.order
        self._scheduled.append((handle, event))
        self._sync_pending()
        return event

    def _boundary(self, reason, request=None):
        self.unsupported_reason = reason
        if request:
            request["unsupported_reason"] = reason
        cancelled = []
        for handle, event in self._scheduled:
            if self.clock.cancel(handle):
                event["status"] = "cancelled"
                event["cancelled_at_s"] = self.clock.now / 1000
                event["cancellation_reason"] = "subset_boundary_cleanup; not an upstream cancellation rule"
                cancelled.append(event["event_id"])
                for earlier in self.requests:
                    if earlier["request_id"] == event["request_id"]:
                        earlier["unsupported_reason"] = reason
        event = self._event("unsupported_visual_boundary", request,
                            details={"reason": reason, "cancelled_event_ids": cancelled,
                                     "cancellation_policy": "stop unsupported projection, preserving last confirmed resources"})
        event["source"] = [SOURCES["request"]]
        self._change({"unsupported_reason": reason}, event["event_type"], event)
        event["state_after"] = deepcopy(self.state)
        return request

    def _geometry(self, eye, location):
        dx, dy = location["x"] - eye[0], location["y"] - eye[1]
        pixels = math.hypot(dx, dy)
        degrees = math.degrees(math.atan((pixels / self.parameters.value("pixels_per_inch")) /
                                         self.parameters.value("viewing_distance_in")))
        theta = 0.0 if pixels == 0 else math.atan2(dy, dx)
        if not all(math.isfinite(v) for v in (pixels, degrees, theta)):
            fail("vision.geometry", "geometry overflowed finite range")
        return degrees, theta, pixels

    def _recognition(self, degrees):
        p = self.parameters
        try:
            duration = (p.value("visual_encoding_factor_s") * -math.log(p.value("visual_object_frequency")) *
                        math.exp(degrees * p.value("visual_encoding_exponent_per_deg")))
        except OverflowError:
            fail("vision.encoding", "encoding duration overflowed finite range")
        if not math.isfinite(duration):
            fail("vision.encoding", "encoding duration overflowed finite range")
        return duration

    def request(self, bound_location, dependencies=()):
        if not isinstance(bound_location, dict):
            fail("vision.location", "expected a bound location object")
        for key in ("chunk_id", "target", "value", "kind"):
            if type(bound_location.get(key)) is not str or not bound_location[key]:
                fail("vision.location." + key, "expected a nonempty string")
        location = deepcopy(bound_location)
        for key in ("x", "y"):
            location[key] = finite_coordinate(location.get(key), "vision.location." + key)
        request = {"request_id": f"attention-{len(self.requests)}", "location": location,
                   "requested_at_s": self.clock.now / 1000, "event_ids": [], "completed": False,
                   "encoding_completed": False, "unsupported_reason": None}
        self.requests.append(request)
        if self.unsupported_reason:
            return self._boundary("vision module already crossed an unsupported boundary", request)
        if self.has_pending_events or self.visual_state != "free":
            return self._boundary("overlapping attention request: source prep replacement, shared encoding target and execution jam are outside this static subset", request)
        if not self._present(location):
            return self._boundary("bound visual object is absent; get-obj-at-location fallback/replacement is outside this static subset", request)
        degrees, theta, pixels = self._geometry(self.state["eye_location"], location)
        duration = self._recognition(degrees)
        self._location = location
        self._shift_duration_s = duration
        event = self._event("visual_attention_request", request, dependencies=dependencies,
                            details={"eccentricity_deg": degrees, "distance_px": pixels,
                                     "frequency": self.parameters.value("visual_object_frequency"),
                                     "frequency_source": "default; string value, empty registration table",
                                     "raw_encoding_s": duration, "randomize_time": False,
                                     "gaussian_noise": False})
        event["source"] = [SOURCES["request"], SOURCES["encoding"], SOURCES["noise"]]
        self._change({"visual_processor": "busy", "moving_attention": request["request_id"],
                      "attended_target": None, "attention_failure": False,
                      "visual_completion_time_s": None}, "visual_attention_request", event)
        self._initiate(request, duration, degrees, theta, dependencies=(event["event_id"],))
        event["state_after"] = deepcopy(self.state)
        return request

    def _initiate(self, request, recognition_s, degrees, theta, dependencies):
        previous = self._last_prepared
        features = 3 if previous is None else (int(abs(degrees - previous["distance_deg"]) >= 2.0) +
                                              int(abs(theta - previous["direction_rad"]) >= math.pi / 4))
        p = self.parameters
        prep_s = features * p.value("eye_feature_prep_s")
        execution_s = (p.value("eye_initiation_s") + degrees * p.value("eye_saccade_rate_s_per_deg") +
                       p.value("eye_saccade_base_s"))
        milliseconds(prep_s)
        milliseconds(execution_s)
        movement = {"distance_deg": degrees, "direction_rad": theta, "preparation_s": prep_s,
                    "execution_s": execution_s, "request_id": request["request_id"],
                    "features_to_prepare": features}
        self._last_prepared = movement
        self._shift_start_s = self.clock.now / 1000
        preparation = self._schedule("eye_preparation_complete", prep_s,
            lambda event: self._prepared(request, event), request, [SOURCES["preparation"]],
            dependencies=dependencies, details={**movement, "raw_remaining_encoding_s": recognition_s,
                                                "encoding_scheduled": recognition_s <= prep_s + execution_s})
        self._change({"visual_preparation": "busy", "last_prepared": movement}, "eye_preparation_started", preparation)
        if recognition_s <= prep_s + execution_s:
            self._schedule("visual_encoding_complete", max(0.0, recognition_s),
                lambda event: self._encoded(request, event), request, [SOURCES["encoding"]],
                dependencies=dependencies, details={"raw_encoding_s": recognition_s,
                    "scheduling_condition": "raw recognition <= raw preparation + execution"})

    def _prepared(self, request, event):
        self._change({"visual_preparation": "free"}, "eye_preparation_complete", event)
        if self._last_prepared is not None:
            self._execution_queue.append((deepcopy(self._last_prepared), request, event["event_id"]))
        self._maybe_execute()

    def _maybe_execute(self):
        if self._execution_queue and self.state["visual_execution"] == "free":
            movement, request, dependency = self._execution_queue.pop(0)
            p = self.parameters
            radius = round(p.value("viewing_distance_in") * math.tan(math.radians(movement["distance_deg"])) *
                           p.value("pixels_per_inch"))
            eye, theta = self.state["eye_location"], movement["direction_rad"]
            landing = [float(round(eye[0] + radius * math.cos(theta))),
                       float(round(eye[1] + radius * math.sin(theta)))]
            complete = self._schedule("eye_movement_complete", movement["execution_s"],
                lambda event: self._eye_complete(request, movement, landing, event), request,
                [SOURCES["execution"], SOURCES["geometry"]], dependencies=(dependency,),
                details={"landing_location": landing, "raw_execution_s": movement["execution_s"],
                         "initiation_included_s": p.value("eye_initiation_s"),
                         "radial_pixels_rounded": radius})
            self._change({"visual_execution": "busy", "next_eye_location": landing}, "eye_execution_started", complete)

    def _eye_complete(self, request, movement, landing, event):
        self._change({"eye_location": landing}, "eye_movement_complete", event)
        if not self._present(request["location"]):
            self._boundary("visual object disappeared during eye movement; dynamic visicon re-encoding is outside scope", request)
            return
        if self.state["moving_attention"] == movement["request_id"]:
            if not self._shift_duration_s or self._shift_duration_s <= 0:
                self._boundary("zero recognition denominator while attention remains active", request)
                return
            degrees, theta, _ = self._geometry(landing, self._location)
            elapsed = self.clock.now / 1000 - self._shift_start_s
            remaining = self._recognition(degrees) * (1.0 - elapsed / self._shift_duration_s)
            event["details"].update(elapsed_since_shift_s=elapsed,
                                     previous_raw_encoding_s=self._shift_duration_s,
                                     raw_remaining_encoding_s=remaining)
            self._shift_duration_s = remaining
            self._initiate(request, remaining, degrees, theta, dependencies=(event["event_id"],))
        self._change({"visual_execution": "free"}, "eye_execution_release", event)
        self._maybe_execute()

    def _encoded(self, request, event):
        if not self._present(request["location"]):
            self._boundary("visual object disappeared before encoding; fallback object lookup is outside scope", request)
            return
        request["encoding_completed"] = True
        self._change({"moving_attention": None, "visual_execution": "free", "visual_processor": "free",
                      "visual_completion_time_s": self.clock.now / 1000,
                      "attended_target": request["location"]["target"]}, "visual_encoding_complete", event)

        def write_buffer(write):
            self._change({"visual_content": request["location"]["target"], "visual_object": request["location"],
                          "visual_requested": True}, "visual_buffer_write", write)

        self._schedule("visual_buffer_write", 0, write_buffer, request, [SOURCES["buffer"]],
                       dependencies=(event["event_id"],), priority=10)

    def clear(self, *, clear_buffer=False):
        """Module clear: literal .050 s preparation; pending eye calls persist.

        Do not silently clear the visual buffer unless the controller explicitly
        requests that separate buffer operation. Re-entrant clear during visual
        preparation is outside this bounded module (upstream check-jam warns).
        """
        if self.unsupported_reason:
            return None
        if self.state["visual_preparation"] == "busy":
            self._boundary("visual clear during preparation: upstream jam/after-method interaction is outside scope")
            return None
        self._last_prepared = None
        self._execution_queue.clear()
        event = self._event("visual_clear_request", None,
                            details={"clear_delay_s": .05, "buffer_clear_requested": clear_buffer,
                                     "cancels_pending_eye_events": False})
        event["source"] = [SOURCES["clear"]]
        # vision's clear :after always calls remove-tracking, which frees exec
        # even without tracking. It does not delete a pending eye-complete call.
        changes = {"visual_preparation": "busy", "visual_execution": "free",
                   "moving_attention": None, "last_prepared": None,
                   "attended_target": None, "attention_failure": False}
        if clear_buffer:
            changes.update(visual_content=None, visual_object=None, visual_requested=False)
        self._change(changes, "visual_clear_request", event)
        complete = self._schedule("visual_clear_complete", .05,
            lambda done: self._change({"visual_preparation": "free"}, "visual_clear_complete", done),
            None, [SOURCES["clear"]], dependencies=(event["event_id"],))
        event["state_after"] = deepcopy(self.state)
        return complete
