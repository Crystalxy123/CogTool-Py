"""Shared projection of CogTool 1.3's ACT-R motor lifecycle.

Derived motor formulas and state transitions: ACT-R authors / CMU 2005–2013,
LGPL-2.1-or-later (NOTICE.md). Python implementation dated 2026-09-26.
The old serial adapter remains unchanged in scope. The opt-in keyboard profile
adds source virtual hands, key mappings and a FIFO motor execution queue for
the integrated controller. Productions and vision belong to that controller.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import hashlib
import heapq
import json
import math
import time

from . import UPSTREAM, __version__, source
from .models import KEYBOARD_DEFAULTS, MOTOR_ENGINE, Project, Task, fail

VERSION = "0.1.0"
MOTOR = "lisp/actr6/core-modules/motor.lisp"
PM = "lisp/actr6/support/general-pm.lisp"
COGTOOL = "java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp"
SOURCES = {
    "preparation": source(PM, "compute-prep-time:650-655;num-to-prepare:752-757"),
    "preparation_override": source(COGTOOL, "prepare-movement:55-69"),
    "features": source(MOTOR, "distance=:402-406;direction=:409-413;feat-differences:494-498,515-525"),
    "lifecycle": source(COGTOOL, "preparation-complete:101-111;perform-movement:117-132;initiation-complete:154-156;finish-movement:173-176"),
    "cursor": source(MOTOR, "compute-exec-time(ply):612-615;move-cursor:721-761"),
    "punch": source(MOTOR, "punch:480-498;click-mouse:790-801"),
    "release": source(PM, "compute-finish-time:700-701"),
    "clock": source("lisp/actr6/framework/misc-utils.lisp", "seconds->ms:349-351"),
    "queue": source("lisp/actr6/framework/scheduling.lisp", "compare-events:823-860;schedule-event-relative:967-968"),
    "keyboard": source("lisp/actr6/framework/device-interface.lisp", "populate-key-to-command-ht:640-733") + "; " + source(COGTOOL, "additional-key-mappings:333-341;press-key:205-222"),
    "key_encoding": source("java/edu/cmu/cs/hcii/cogtool/model/ACTRPredictionAlgo.java", "encodeKey:1100-1192"),
    "peck_recoil": source(MOTOR, "compute-exec/finish-time(peck-recoil):557-580"),
    "hand": source(MOTOR, "home-hands:363-377;hand-ply:622-635;hand-to-mouse:858-862") + "; " + source(COGTOOL, "hand-to-home:82-94"),
    "execution_queue": source(PM, "check-jam:304-311;maybe-execute-movement:535-537") + "; " + source(COGTOOL, "preparation-complete:101-111;finish-movement:173-176"),
}


def milliseconds(seconds: float) -> int:
    """Round each relative delay, not the final task sum (CL ROUND ties-even)."""
    if not math.isfinite(seconds) or seconds < 0 or not math.isfinite(seconds / .001):
        fail("experimental motor time", "relative delay is outside finite nonnegative range")
    return round(seconds / .001)


@dataclass(frozen=True)
class Movement:
    style: str
    distance_deg: float = 0.0
    direction_rad: float = 0.0
    hand: str = "right"
    finger: str = "index"


def _movement_style(movement):
    return "ply" if movement.style in {"cursor", "home"} else movement.style


def changed_features(previous: Movement | None, current: Movement) -> int:
    """Source movement-style feature memory, shared by mouse and keyboard.

    Width is not a motor preparation feature. The upstream direction comparison
    uses absolute difference without angle wrapping, including at +/- pi.
    """
    style = _movement_style(current)
    if previous is None or _movement_style(previous) != style:
        return {"ply": 4, "punch": 3, "peck_recoil": 5}[style]
    if current.style == "punch":
        if previous.hand != current.hand:
            return 2
        if previous.finger != current.finger:
            return 1
        return 0
    maximum = 4 if style == "ply" else 5
    if previous.hand != current.hand:
        return maximum - 1
    # Both cursor-ply and hand-ply inherit the same DUMMY finger.
    if style != "ply" and previous.finger != current.finger:
        return maximum - 2
    return int(abs(current.distance_deg - previous.distance_deg) >= 2.0) + int(
        abs(current.direction_rad - previous.direction_rad) >= math.pi / 4)


_FINGER_OFFSETS = {
    "left": {"index": [0, 0], "middle": [-1, 0], "ring": [-2, 0], "pinkie": [-3, 0], "thumb": [1, 2]},
    "right": {"index": [0, 0], "middle": [1, 0], "ring": [2, 0], "pinkie": [3, 0], "thumb": [-1, 2]},
}
# Actual device-interface lookup values (including source-rounded polar values),
# not KeyboardUtil's separate frontend table. CogTool's :after adds four rows.
_KEY_COMMANDS = {
    "space": ("left", "thumb", 0, 0),
    "backquote": ("left", "pinkie", 2.24, -2.03), "tab": ("left", "pinkie", 1.41, -2.36),
    "1": ("left", "pinkie", 2, -1.57), "Q": ("left", "pinkie", 1, -1.57),
    "A": ("left", "pinkie", 0, 0), "Z": ("left", "pinkie", 1, 1.57),
    "2": ("left", "ring", 2, -1.57), "W": ("left", "ring", 1, -1.57),
    "S": ("left", "ring", 0, 0), "X": ("left", "ring", 1, 1.57),
    "3": ("left", "middle", 2, -1.57), "E": ("left", "middle", 1, -1.57),
    "D": ("left", "middle", 0, 0), "C": ("left", "middle", 1, 1.57),
    "4": ("left", "index", 2, -1.57), "R": ("left", "index", 1, -1.57),
    "F": ("left", "index", 0, 0), "V": ("left", "index", 1, 1.57),
    "5": ("left", "index", 2.24, -1.11), "T": ("left", "index", 1.41, -.79),
    "G": ("left", "index", 1, 0), "B": ("left", "index", 1.41, .79),
    "6": ("right", "index", 2.24, -2.03), "Y": ("right", "index", 1.41, -2.36),
    "H": ("right", "index", 1, 3.14), "N": ("right", "index", 1.41, 2.36),
    "7": ("right", "index", 2, -1.57), "U": ("right", "index", 1, -1.57),
    "J": ("right", "index", 0, 0), "M": ("right", "index", 1, 1.57),
    "8": ("right", "middle", 2, -1.57), "I": ("right", "middle", 1, -1.57),
    "K": ("right", "middle", 0, 0), "comma": ("right", "middle", 1, 1.57),
    "9": ("right", "ring", 2, -1.57), "O": ("right", "ring", 1, -1.57),
    "L": ("right", "ring", 0, 0), "period": ("right", "ring", 1, 1.57),
    "0": ("right", "pinkie", 2, -1.57), "P": ("right", "pinkie", 1, -1.57),
    "semicolon": ("right", "pinkie", 0, 0), "slash": ("right", "pinkie", 1, 1.57),
    "hyphen": ("right", "pinkie", 2.24, -1.11), "[": ("right", "pinkie", 1.41, -.78),
    "quote": ("right", "pinkie", 1, 0), "return": ("right", "pinkie", 2, 0),
    "=": ("right", "pinkie", 2.83, -.78), "]": ("right", "pinkie", 2.24, -.46),
    "backslash": ("right", "pinkie", 3.16, -.32), "delete": ("right", "pinkie", 3.87, -.59),
}
_KEY_ALIASES = {" ": "space", ",": "comma", ".": "period", "/": "slash", ";": "semicolon",
                "'": "quote", "`": "backquote", "-": "hyphen", "=": "hyphen", "[": "P", "]": "P",
                "\\": "backslash", "ENTER": "return", "BACKSPACE": "delete", "DELETE": "delete",
                "ESC": "Q", "UP": "slash", "DOWN": "slash", "LEFT": "slash", "RIGHT": "slash"}


def key_command(key):
    """Finite unshifted frontend key -> actual pinned backend motor command."""
    if type(key) is not str:
        fail("motor.key", "expected an unshifted key string")
    if len(key) == 1 and ("a" <= key <= "z" or "0" <= key <= "9"):
        backend = key.upper()
    else:
        backend = _KEY_ALIASES.get(key)
    if backend not in _KEY_COMMANDS:
        fail("motor.key", f"unsupported unshifted key {key!r}; no baseline fallback")
    hand, finger, radius, theta = _KEY_COMMANDS[backend]
    return {"backend_key": backend, "hand": hand, "finger": finger,
            "movement": Movement("peck_recoil" if radius else "punch", radius, theta, hand, finger)}


@dataclass
class ScheduledEvent:
    """A cancellable pending call; module traces own cancellation evidence."""
    when_ms: int
    order: int
    cancelled: bool = False
    executed: bool = False
    _clock: object = field(default=None, repr=False, compare=False)


class Clock:
    """Shared relative scheduler: milliseconds, descending priority, FIFO ties.

    Numeric priorities retain the old motor queue semantics. :min/:max match
    the fixed upstream scheduler's symbolic extrema; controllers may execute
    one event at a time and enforce their own explicit stop/step/time bounds.
    """
    def __init__(self):
        self.now = 0
        self.order = 0
        self.queue = []

    def schedule(self, delay_s, callback, priority=0):
        rank = {":min": -math.inf, ":max": math.inf}.get(priority, priority)
        if isinstance(rank, bool) or not isinstance(rank, (int, float)) or math.isnan(rank):
            fail("event priority", "expected numeric priority or :min/:max")
        when = self.now + milliseconds(delay_s)
        heapq.heappush(self.queue, (when, -rank, self.order, callback))
        self.order += 1
        return when

    def schedule_event(self, delay_s, callback, priority=0):
        """Schedule a cancellable call without changing legacy schedule()."""
        event = ScheduledEvent(0, self.order, _clock=self)

        def execute():
            event.executed = True
            callback()

        event.when_ms = self.schedule(delay_s, execute, priority=priority)
        return event

    def cancel(self, event):
        """Remove a pending call, as delete-event does upstream (1408–1425).

        Removing it physically keeps queue peeks, time bounds and queue-end
        checks independent of cancelled deadlines. No simulated time elapses.
        """
        if not isinstance(event, ScheduledEvent):
            fail("event cancellation", "expected a ScheduledEvent handle")
        if event._clock is not self or event.cancelled or event.executed:
            return False
        for index, entry in enumerate(self.queue):
            if entry[2] == event.order:
                self.queue.pop(index)
                heapq.heapify(self.queue)
                event.cancelled = True
                return True
        return False

    def step(self):
        """Run one queued callback; False means no event, not task success."""
        if not self.queue:
            return False
        self.now, _, _, callback = heapq.heappop(self.queue)
        callback()
        return True

    def drain(self):
        while self.step():
            pass


# Retain the previous private name for existing callers and regression tests.
_Clock = Clock


class MotorModule:
    """The shared, nonblocking motor component, independent of command issue.

    request never drains the injected clock. Callbacks receive
    on_state_change(module, change_record) and on_complete(module, handle).
    The handle's event_ids/completion_event_ids are populated as preparation
    schedules execution. Completion means all that request's events finished,
    including a late output under unusual modeler-supplied parameter values.

    The old profile retains its serial adapter's single request in flight.
    The optional keyboard profile shares preparation memory and a FIFO motor
    execution queue: preparation may overlap execution; executions do not.
    prepare permits punch preparation during an earlier movement without output.
    Buffer contents belong to the controller; manual_state derives only the
    motor module's three resource flags.
    """
    def __init__(self, project: Project, task: Task, clock=None):
        initial = task.demonstration.initial
        self.project, self.task = project, task
        self.context = f"task[{task.id}]"
        self.keyboard_enabled = KEYBOARD_DEFAULTS.keys() <= project.parameters.entries.keys()
        if initial.mouse_hand != "right" or (initial.hand != "mouse" and not self.keyboard_enabled):
            fail(self.context + ".initial", "motor subset requires right hand already on mouse; no homing fallback")
        self.parameters = project.parameters
        self.clock = clock if clock is not None else Clock()
        self.events, self.state_changes = [], []
        self.state = {"mouse": list(initial.mouse), "frame": initial.frame, "focus": initial.focus,
                      "motor_preparation": "free", "motor_processor": "free", "motor_execution": "free",
                      "last_prepared": None, "open_menu": None, "last_click": None}
        self.last_prepared = None
        self.active_request = None
        self._pending_requests = []
        self._execution_queue = []
        self._init_stamp_s = -.1
        if self.keyboard_enabled:
            self.state.update(hand=initial.hand,
                hand_locations={"left": [4, 4], "right": [28, 2] if initial.hand == "mouse" else [7, 4]},
                finger_offsets=deepcopy(_FINGER_OFFSETS), last_key=None)

    @property
    def manual_state(self):
        return "busy" if any(self.state[key] == "busy" for key in
                             ("motor_preparation", "motor_processor", "motor_execution")) else "free"

    def _update(self, changes, trigger, event_id, observer):
        before = deepcopy(self.state)
        self.state.update(deepcopy(changes))
        record = {"index": len(self.state_changes), "time_s": self.clock.now / 1000,
                  "trigger": trigger, "event_id": event_id,
                  "before": before, "after": deepcopy(self.state)}
        self.state_changes.append(record)
        if observer is not None:
            observer(self, record)

    def _event(self, step, kind, resource, delay, dependencies, changes, sources,
               handle, observer, after=None, details=None):
        event = {"index": len(self.events), "event_id": f"motor-{len(self.events)}",
                 "step_index": step.index, "demo_index": step.demo_index,
                 "original_action_id": None, "op": step.op, "origin": step.origin,
                 "event_type": kind, "resource": resource, "target": step.target,
                 "start_s": self.clock.now / 1000, "end_s": None, "duration_s": None,
                 "dependencies": list(dependencies), "state_before": deepcopy(self.state),
                 "state_after": None, "source": list(sources), "details": details or {}}
        self.events.append(event)
        handle["event_ids"].append(event["event_id"])

        def complete():
            self._update(changes, kind, event["event_id"], observer)
            event["state_after"] = deepcopy(self.state)
            event["completion_order"] = len(self.state_changes) - 1
            if after is not None:
                after()

        end = self.clock.schedule(delay, complete)
        event["end_s"], event["duration_s"] = end / 1000, (end - self.clock.now) / 1000
        return event

    def prepare(self, step, dependencies=(), *, on_state_change=None, on_complete=None):
        """Prepare right-index punch features, without initiation or output.

        ACTRPredictionAlgo emits prepare(punch), then click-mouse (not execute).
        The later click request prepares the same punch with zero differences.
        Completion here means preparation finished, not a device action.
        """
        path = f"{self.context}.steps[{step.demo_index}]"
        if step.op not in {"click", "right_click"}:
            fail(path + ".op", "prepare supports only click/right_click punch features")
        if self.state["motor_preparation"] == "busy":
            fail(path + ".prepare", "motor features are already being prepared; preparation replacement is unsupported")
        self.project.design.frame(step.frame, path).widget(step.target, path)
        handle = {"event_ids": [], "completion_event_ids": [], "completed": False}
        movement = Movement("punch")
        features = changed_features(self.last_prepared, movement)
        self.last_prepared = movement
        self._update({"motor_preparation": "busy", "motor_processor": "busy",
                      "last_prepared": asdict(movement)}, "prepare_request", None, on_state_change)

        def prepared():
            # CogTool's override checks the unrounded initiation-time parameter
            # against mp-time here; this is not an unconditional proc release.
            if self._init_stamp_s > 0 and self.clock.now / 1000 >= self._init_stamp_s + self.parameters.value("motor_initiation_s"):
                self._update({"motor_processor": "free"}, "prepare_processor_release",
                             preparation["event_id"], on_state_change)
            handle["completed"] = True
            if on_complete is not None:
                on_complete(self, handle)

        preparation = self._event(step, "motor_preparation", "motor.preparation",
            features * self.parameters.value("motor_feature_prep_s"), dependencies,
            {"motor_preparation": "free"},
            [SOURCES["preparation"], SOURCES["preparation_override"], SOURCES["features"],
             source(PM, "prepare:548-551"), source(COGTOOL, "preparation-complete:101-111")],
            handle, on_state_change, prepared,
            {"features_to_prepare": features, "movement": asdict(movement),
             "feature_prep_s": self.parameters.value("motor_feature_prep_s"),
             "exec_immediate": False, "command": "prepare"})
        handle["completion_event_ids"] = [preparation["event_id"]]
        return handle

    def request(self, step, dependencies=(), *, on_state_change=None, on_complete=None):
        from .engine import point_time

        if self.active_request is not None and not self.keyboard_enabled:
            fail(self.context, "motor command already in flight; movement execution queues are unsupported")
        if self.state["motor_preparation"] == "busy":
            fail(self.context, "motor features are already being prepared; wait for preparation completion")
        supported = {"point", "click", "right_click", "think", "wait", "transition"}
        if self.keyboard_enabled:
            supported |= {"key", "home"}
        if step.op not in supported:
            fail(f"{self.context}.steps[{step.demo_index}].op", f"{step.op!r} is outside motor subset; no baseline fallback")
        if step.op == "transition" and step.state_after["frame"] != step.frame:
            fail(f"{self.context}.steps[{step.demo_index}].transition", "motor subset supports self-loop transitions only; visual frame reset is unimplemented")
        handle = {"event_ids": [], "completion_event_ids": [], "completed": False}
        p, clock, state = self.parameters, self.clock, self.state

        def done():
            handle["completed"] = True
            self._pending_requests = [pending for pending in self._pending_requests if pending is not handle]
            self.active_request = self._pending_requests[0] if self._pending_requests else None
            if on_complete is not None:
                on_complete(self, handle)

        def register():
            self._pending_requests.append(handle)
            self.active_request = self._pending_requests[0]

        if step.op in {"think", "wait", "transition"}:
            if self.active_request is not None:
                fail(self.context, "serial nonmotor blocks cannot be submitted while a motor request is pending")
            register()
            changes = {"frame": step.state_after["frame"], "focus": step.state_after["focus"]}
            event = self._event(step, step.op, {"think": "cognitive", "wait": "system", "transition": "system"}[step.op],
                                step.duration_s, dependencies, changes, [step.source, SOURCES["clock"]],
                                handle, on_state_change, done,
                                {"policy": "explicit serial script block; no production selection or resource overlap inferred"})
            handle["completion_event_ids"] = [event["event_id"]]
            return handle

        widget = (self.project.design.frame(step.frame, self.context).widget(step.target, self.context)
                  if step.op not in {"key", "home"} else None)
        if self.keyboard_enabled and step.op in {"point", "click", "right_click"} and state["hand_locations"]["right"] != [28, 2]:
            fail(self.context, "mouse command requires right hand at mouse; explicit homing required")
        if step.op == "key":
            command = key_command(step.key)
            movement = command["movement"]
            if movement.style == "punch":
                output_delay = p.value("motor_initiation_s") + p.value("motor_key_closure_s")
                finish_delay = p.value("motor_initiation_s") + 2 * p.value("motor_burst_s")
                formula = "punch: output=I+closure; release=I+2*burst"
                sources = [SOURCES["punch"]]
            else:
                movement_time = max(p.value("motor_burst_s"), p.value("fitts_min_s"),
                    p.value("motor_peck_fitts_coefficient_s") * math.log2(movement.distance_deg + .5))
                output_delay = p.value("motor_initiation_s") + movement_time
                finish_delay = output_delay + p.value("motor_burst_s") + movement_time
                formula = "peck-recoil: M=max(burst,minFitts,peck_b*log2(r+.5)); output=I+M; release=I+2*M+burst"
                sources = [SOURCES["peck_recoil"]]
            output_kind, finish_kind = "key_output", "key_finish"
            output_changes = {}
            details = {"formula": formula, "requested_key": step.key, "backend_key": command["backend_key"],
                       "hand": movement.hand, "finger": movement.finger, "key_s_used": False}
            sources += [SOURCES["keyboard"], SOURCES["key_encoding"]]
        elif step.op == "home":
            if step.device not in {"keyboard", "mouse"}:
                fail(self.context + ".home.device", "expected keyboard or mouse")
            target = [7, 4] if step.device == "keyboard" else [28, 2]
            start = state["hand_locations"]["right"]
            if step.device == "mouse" and start == target:
                register()
                event = self._event(step, "hand_noop", "motor", 0, dependencies, {},
                    [SOURCES["hand"]], handle, on_state_change, done,
                    {"reason": "hand-to-mouse vpt=; already at mouse; preparation unchanged"})
                handle["completion_event_ids"] = [event["event_id"]]
                return handle
            radius = math.dist(start, target)
            theta = math.atan2(target[1] - start[1], target[0] - start[0]) if radius else 0
            movement = Movement("home", radius, theta)
            fitts = max(p.value("fitts_min_s"), p.value("fitts_coefficient_s") * math.log2(radius / 4 + .5))
            output_delay = p.value("motor_initiation_s") + fitts
            finish_delay = output_delay + p.value("motor_burst_s")
            output_kind, finish_kind = "hand_move", "hand_finish"
            output_changes = {"hand": step.device, "hand_locations": {**deepcopy(state["hand_locations"]), "right": target}}
            sources = [SOURCES["hand"], SOURCES["cursor"], SOURCES["release"]]
            details = {"formula": "F=max(minFitts,mouse_b*log2(D/4+.5)); output=I+F; release=I+F+burst",
                       "from": list(start), "to": target, "distance_keyboard_units": radius,
                       "target_width_keyboard_units": 4, "homing_s_used": False}
        elif step.op == "point":
            try:
                output_delay, details = point_time(state["mouse"], widget, p)
            except (ValueError, OverflowError, ZeroDivisionError) as exc:
                fail(f"{self.context}.steps[{step.demo_index}].point", str(exc))
            if details["distance_px"] == 0:
                register()
                event = self._event(step, "cursor_noop", "motor", 0, dependencies, {},
                                    [SOURCES["cursor"]], handle, on_state_change, done,
                                    {"reason": "zero distance; last preparation unchanged"})
                handle["completion_event_ids"] = [event["event_id"]]
                return handle
            movement = Movement("cursor", details["distance_deg"],
                                math.atan2(widget.center[1] - state["mouse"][1], widget.center[0] - state["mouse"][0]))
            finish_delay = output_delay + p.value("motor_burst_s")
            output_changes = {"mouse": list(widget.center)}
            output_kind, finish_kind = "cursor_move", "cursor_finish"
            details.pop("omits", None)
            details["formula"] = "output=initiation+Fitts; release=output+burst, both relative to perform"
            sources = [SOURCES["cursor"], SOURCES["release"]]
        else:
            movement = Movement("punch")
            output_delay = p.value("motor_initiation_s") + p.value("motor_key_closure_s")
            finish_delay = p.value("motor_initiation_s") + 2 * p.value("motor_burst_s")
            output_kind, finish_kind = "click_output", "click_finish"
            output_changes = {"focus": step.state_after["focus"],
                              "last_click": {"target": step.target, "button": "right" if step.op == "right_click" else "left"}}
            if step.op == "right_click":
                output_changes["open_menu"] = widget.id
            elif widget.kind == "menu_item":
                output_changes["open_menu"] = None
            sources = [SOURCES["punch"]]
            details = {"formula": "output=initiation+closure; release=initiation+2*burst, both relative to perform",
                       "button": output_changes["last_click"]["button"],
                       "hand": "right", "finger": "index", "click_s_used": False}

        # Reject unrepresentable timing before changing any module resources.
        for delay in (output_delay, finish_delay):
            milliseconds(delay)
        register()
        features = changed_features(self.last_prepared, movement)
        self.last_prepared = movement
        self._update({"motor_preparation": "busy", "motor_processor": "busy",
                      "last_prepared": asdict(movement)}, "movement_request", None, on_state_change)

        def perform():
            self._update({"motor_processor": "busy", "motor_execution": "busy"}, "perform_movement", None, on_state_change)
            self._init_stamp_s = clock.now / 1000
            dependency = [preparation["event_id"]]
            remaining = 3

            if step.op == "key":
                # The upstream queue-output-events method resolves the finger
                # position at perform time, after any previously queued homing.
                home = [7, 4] if movement.hand == "right" else [4, 4]
                if state["hand_locations"][movement.hand] != home:
                    fail(self.context + ".key", "pressed hand is not at keyboard home position")
                loc = state["hand_locations"][movement.hand]
                offset = state["finger_offsets"][movement.hand][movement.finger]
                coordinates = [round(loc[0] + offset[0] + movement.distance_deg * math.cos(movement.direction_rad)),
                               round(loc[1] + offset[1] + movement.distance_deg * math.sin(movement.direction_rad))]
                details["coordinates"] = coordinates
                output_changes["last_key"] = {"requested_key": step.key, "backend_key": command["backend_key"],
                                              "coordinates": coordinates}

            def component_complete():
                nonlocal remaining
                remaining -= 1
                if remaining == 0:
                    done()

            initiation = self._event(step, "motor_initiation", "motor.processor", p.value("motor_initiation_s"),
                                     dependency, {"motor_processor": "free"}, [SOURCES["lifecycle"]],
                                     handle, on_state_change, component_complete)
            # All deadlines are relative to perform; these are not additive.
            output = self._event(step, output_kind, "motor.pending_output", output_delay,
                                 dependency, output_changes, sources, handle, on_state_change,
                                 component_complete, details)
            def finish_complete():
                component_complete()
                self._maybe_execute()

            finish = self._event(step, finish_kind, "motor.execution", finish_delay,
                                 dependency, {"motor_execution": "free"}, sources + [SOURCES["lifecycle"]],
                                 handle, on_state_change, finish_complete)
            handle["completion_event_ids"] = [initiation["event_id"], output["event_id"], finish["event_id"]]

        def prepared():
            self._execution_queue.append(perform)
            self._maybe_execute()

        preparation = self._event(step, "motor_preparation", "motor.preparation", features * p.value("motor_feature_prep_s"),
                                   dependencies, {"motor_preparation": "free"},
                                   [SOURCES["preparation"], SOURCES["preparation_override"], SOURCES["features"]],
                                   handle, on_state_change, prepared,
                                   {"features_to_prepare": features, "movement": asdict(movement),
                                    "feature_prep_s": p.value("motor_feature_prep_s")})
        return handle

    def _maybe_execute(self):
        """Source maybe-execute-movement: FIFO, only when execution is free."""
        if self._execution_queue and self.state["motor_execution"] == "free":
            self._execution_queue.pop(0)()


def predict_motor_subset(project: Project, task: Task, script, started: float) -> dict:
    """Original 0.1 serial adapter over the shared nonblocking motor module."""
    from .io import implementation_fingerprint, input_hash

    initial = task.demonstration.initial
    context = f"task[{task.id}]"
    module = MotorModule(project, task)
    supported = {"point", "click", "right_click", "think", "wait", "transition"}
    for step in script.steps:
        if step.op not in supported:
            fail(f"{context}.steps[{step.demo_index}].op", f"{step.op!r} is outside motor subset; no baseline fallback")
        if step.op == "transition" and step.state_after["frame"] != step.frame:
            fail(f"{context}.steps[{step.demo_index}].transition", "motor subset supports self-loop transitions only; visual frame reset is unimplemented")

    p, clock = project.parameters, module.clock
    last_dependency = []
    for step in script.steps:
        handle = module.request(step, last_dependency)
        clock.drain()
        last_dependency = handle["completion_event_ids"]
    events, state_changes, state = module.events, module.state_changes, module.state

    model_hash, implementation = input_hash(project), implementation_fingerprint()
    fingerprint = hashlib.sha256(json.dumps({"implementation_sha256": implementation["sha256"],
        "input_sha256": model_hash, "task_id": task.id, "engine_version": VERSION},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return {
        "result_schema_version": 1, "software": "CogTool-Py", "software_version": __version__,
        "engine": {"name": MOTOR_ENGINE, "version": VERSION}, "upstream": UPSTREAM,
        "project_id": project.id, "task_id": task.id, "input_sha256": model_hash,
        "implementation": implementation, "execution_fingerprint": fingerprint,
        "parameters": p.result_dict(), "unused_parameters": ["click_s", "key_s", "homing_s"],
        "predicted_time_s": clock.now / 1000, "time_unit": "s", "program_runtime_s": time.perf_counter() - started,
        "initial_state": asdict(initial), "final_state": script.final_state,
        "initial_visual_state": None, "final_motor_state": state,
        "demonstration": [s.to_dict() for s in task.demonstration.steps],
        "steps": [asdict(s) for s in script.steps], "events": events, "state_changes": state_changes,
        "timing_boundary": "t=0 issues first serial script command; next command waits for its queue to drain; end when final command queue is empty",
        "scheduler": {"quantum_s": .001, "rounding": "ties-to-even per relative delay",
                      "same_time_order": "priority descending then FIFO insertion order; motor events priority 0",
                      "task_end": "all serial script commands issued and no pending events",
                      "resource_interval_durations_are_not_additive": True},
        "sources": SOURCES,
        "validation": {"original_comparison": "unverified", "differential_tests": "not_executed",
                       "claim": "independently tested motor lifecycle projection of pinned 2014 source; not complete ACT-R or 2009 equivalence"},
        "scope": ["right hand already on mouse; deterministic randomize-time=nil/cursor-noise=nil",
                  "known rectangular targets; point, single click, initially closed single-level context menu",
                  "shared generator; explicit/generated Think and serial waits; self-loop transitions only",
                  "serial command issue; motor preparation memory, initiation, output and release deadlines"],
        "omissions": ["production selection/firing and FIND/LOOK-AT rules", "visual buffers and EMMA",
                      "prepare-click lookahead and inter-command overlap", "upstream stop production and front-end regeneration",
                      "keyboard, homing, frame changes and general menu state"],
        "warnings": ["experimental diagnostic: not an original CogTool prediction or a validated accuracy claim",
                     "shared generated-step notes describe baseline assumptions; experimental event sources determine timing",
                     "click_s/key_s/homing_s retained for shared input identity but unused in this engine",
                     "initial visual state unknown and not simulated; no invented FIND/vision delay",
                     "resource intervals overlap; do not sum event durations to obtain task time"],
    }
