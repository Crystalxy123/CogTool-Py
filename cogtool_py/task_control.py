"""Continuation of the same experimental controller, using its shared modules.

CogTool/ACT-R rule adaptations, LGPL-2.1-or-later; CMU/ACT-R authors in NOTICE.
Python changes 2026-09-26. No independent clock, formulas or case-specific times.
"""
from copy import deepcopy
import re

from . import source
from .control_prefix import PrefixController, SOURCES, JAVA, POLICY

SOURCES.update({
    "click": source(JAVA, "visitAction ButtonPress prepare/click:1999-2047"),
    "think": source(JAVA, "generateMental:2601-2626;flushMentalStep:1309-1316"),
    "stop": source(JAVA, "endScript:1786-1800"),
    "writer": source(JAVA, "outputScriptStepState:1233-1268;destination suppression:1535-1559"),
    "device": source("java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp", "set-cogtool-plist:264-285;device-handle-keypress:971-975;device-handle-click:977-981;transition:1037-1049"),
    "startup_clear": source("java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp", "curframe init:825;build-vis-locs-for:891-896;cogtool-run-model:1152") + "; " +
                     source("lisp/actr6/support/general-pm.lisp", "clear:284-292"),
    "termination": source("lisp/actr6/framework/scheduling.lisp", "run-sched-queue:331-387;run:524-559") + "; " +
                   source("java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp", "cogtool-run-model:1155-1161"),
})


class IntegratedController(PrefixController):
    """Compile bounded script templates once; compete on current module state.

    Inherits buffers, location search, production selection/firing scheduling,
    the exact clock and the exact motor module used by the preserved prefix.
    The script is generated once at the public predict boundary. A transition
    annotation is not compiled into a second production or synthetic delay.
    """
    def __init__(self, project, task, script):
        super().__init__(project, task, script)
        from .vision import VisionModule
        self.model_stop = None
        self.first_right_click = None
        self.menu_selection = None
        self.blocker = None
        self.rules = []
        self.step_map = {step.index: step for step in script.steps}
        self.issued_steps = set()
        self.completed_device_steps = set()
        self.transitions = {}
        self.pending_waits = []
        self.wait_active = False
        self.pending_keyboard_transition = None
        self.state["pending_keystrokes"] = 0
        self.initial_frame_id = self.frame.id
        self.vision_context = {}
        self.state["goal_state"] = 1 if self.config.profile == "source_2014_defaults" else 2
        self.state["visual_completion_unmodeled"] = False
        self.vision = VisionModule(project.parameters, self.clock,
                                   visible=lambda target: target in self.visible and self.frame_matches(),
                                   location_present=lambda loc: loc.get("frame", self.frame.id) == self.frame.id and loc["target"] in self.visible,
                                   on_state_change=self.observe_vision,
                                   initial_eye=self.config.initial_eye or (0, 0))
        self.compile_rules()

    def control_finished(self):
        return self.model_stop is not None

    def snapshot(self):
        result = super().snapshot()
        if hasattr(self, "vision"):
            result["vision"] = deepcopy(self.vision.state)
        return result

    def unsupported(self, reason, *, step=None):
        self.failure = "unsupported"
        self.blocker = {"reason": reason, "step_index": step.index if step else None,
                        "demo_index": step.demo_index if step else None,
                        "field": "generated_script" if step else "module_state"}
        self.record("unsupported_integrated_path", details=self.blocker)

    def compile_rules(self):
        state = 2
        counter = 3  # suppression=1, start=2, matching the Java writer order.
        last_look_bounds = None
        current_step_frame = self.frame.id
        keyboard_previous_hand = None
        keyboard_demo = None
        home_pending = False
        word_at = {}
        spelling_execution_free = True

        # These annotations belong to the triggering device output, not an
        # extra production or a serial time block. Upstream adds sideband
        # destination/delay to the final action production (Java1490-1560).
        annotations = set()
        for i, s in enumerate(self.script.steps):
            if s.op != "transition":
                continue
            j=i-1; delay=0.0
            if j >= 0 and self.script.steps[j].op == "wait" and self.script.steps[j].origin == "automatic":
                delay=self.script.steps[j].duration_s;annotations.add(self.script.steps[j].index);j-=1
            previous=self.script.steps[j] if j >= 0 else None
            if previous is None or previous.op not in {"click", "right_click", "key"}:
                self.unsupported("transition must follow its generated triggering device action",step=s);return
            self.transitions[previous.index]={"annotation":s,"delay_s":delay,
                "destination":s.state_after["frame"],
                "delay_label":next((t.delay_label for t in self.project.design.transitions if t.id == s.note),None)}
            annotations.add(s.index)

        def add(name, step, start, end, utility=0, at=None, **properties):
            nonlocal counter, home_pending
            self.rules.append({"name": name, "production_id": f"{name}-{counter}",
                               "order": counter, "utility": utility,
                               "at_s": self.action_time if at is None else at,
                               "state_from": start, "state_to": end,
                               "step_index": step.index if step else None,
                               "target": step.target if step else None,
                               "frame": current_step_frame, **properties})
            counter += 1
            # Java emitProduction clears handToHomePending after each rule;
            # the home visitor sets it again after emitting move-hand.
            home_pending = False

        for index, step in enumerate(self.script.steps):
            current_step_frame = step.frame
            if step.index in annotations:
                continue
            if step.op not in {"point", "right_click", "click", "think", "key", "home", "look_at"}:
                self.unsupported(f"no integrated production template for {step.op!r}", step=step)
                return
            if step.target and step.op != "key":
                widget = self.project.design.frame(step.frame, "integrated compilation").widget(step.target, "integrated compilation")
                if step.op == "look_at" or widget.bounds != last_look_bounds:
                    add("find", step, state, state + 1, utility=-1)
                    add("look-at", step, state, state + 2, branch="direct")
                    add("look-at", step, state + 1, state + 2, branch="after_find")
                    last_look_bounds = widget.bounds
                    state += 2
            if step.op == "point":
                add("find-location", step, state, state, utility=-1)
                add("move-mouse", step, state, state + 1)
                state += 1
            elif step.op in {"click", "right_click"}:
                add("prepare-click", step, state, state + 1)
                add("click-mouse", step, state + 1, state + 2)
                state += 2
            elif step.op == "think":
                add("think", step, state, state + 1, at=step.duration_s)
                state += 1
            elif step.op == "home":
                if "motor_peck_fitts_coefficient_s" not in self.project.parameters.entries:
                    self.unsupported("hand movement requires explicit keyboard motor profile", step=step);return
                add("move-hand",step,state,state+1,device=step.device)
                state += 1
                home_pending=step.device == "keyboard"
            elif step.op == "key":
                if "motor_peck_fitts_coefficient_s" not in self.project.parameters.entries:
                    self.unsupported("keyboard requires explicit keyboard motor profile", step=step);return
                if step.key != "DOWN" and (len(step.key) != 1 or step.key not in "abcdefghijklmnopqrstuvwxyz0123456789"):
                    self.unsupported("integrated keyboard admits lowercase ASCII letters/digits and source-mapped DOWN only; other function keys/chords unsupported",step=step);return
                from .models import LEFT_KEYS
                hand="left" if step.key in LEFT_KEYS else "right"
                if keyboard_demo != step.demo_index or index == 0 or self.script.steps[index-1].op != "key":
                    keyboard_previous_hand=None;keyboard_demo=step.demo_index
                    # handleCharacters resets per TextActionSegment, which may
                    # be split by an inserted mental inside one KeyAction.
                    segment=[]
                    for candidate in self.script.steps[index:]:
                        if candidate.op != "key" or candidate.demo_index != step.demo_index or candidate.frame != step.frame:
                            break
                        segment.append(candidate)
                    # One source codepoint per physical key. Source WORD also
                    # matches runs of private-use DOWN, not the letters D/O/W/N.
                    text="".join("\ue00d" if s.key == "DOWN" else s.key for s in segment)
                    def word_symbol(value):
                        # LispUtil.makeSymbol + original US-ASCII model export.
                        return value.encode("ascii", "replace").decode()  # runtime Lisp symbol print-name, no reader bars
                    word_at={segment[m.start()].index:word_symbol(m.group()) for m in
                             re.finditer(r"[^ -@\[-`\{-~\s]{2,}",text)}
                    spelling_execution_free = not (home_pending and hand=="left")
                if step.index in word_at:
                    add("get-spelling-"+word_at[step.index],step,state,state+1,
                        execution_free=spelling_execution_free)
                    state += 1
                    spelling_execution_free = True
                add("press-key",step,state,state+1,
                    execution_free=keyboard_previous_hand==hand,hand=hand,key=step.key)
                state+=1;keyboard_previous_hand=hand;home_pending=False
        add("stop", None, state, "stop", at=0)

    def candidates(self):
        candidates = []
        goal = self.state["goal_state"]
        if goal == 1:
            candidates.append({"name": "set-start-frame", "production_id": "set-start-frame-2",
                               "utility": 0, "order": 2, "at_s": 0, "state_to": 2,
                               "step_index": None, "target": None})
        if goal != "stop" and self.state["suppress_re_encoding"] and self.visual_free() and self.frame_matches():
            candidates.append({"name": "*suppress-re-encoding", "production_id": "*suppress-re-encoding-1",
                               "utility": 0, "order": 1, "at_s": 0, "step_index": None, "target": None})
        for rule in self.rules:
            if rule["state_from"] != goal:
                continue
            name = rule["name"]
            same_frame = self.state["current_frame"] == rule["frame"]
            visible_frame = same_frame and self.state["frame_visible"]
            location = self.state["visual_location"]
            same = bool(location and rule["target"] in self.locations and
                        location["value"] == self.locations[rule["target"]]["value"])
            if name in {"find", "find-location"}:
                enabled = visible_frame
            elif name == "look-at":
                enabled = visible_frame and same and self.visual_free()
            elif name == "move-mouse":
                enabled = visible_frame and same and self.motor.manual_state == "free"
            elif name == "prepare-click":
                enabled = visible_frame and self.motor.state["motor_preparation"] == "free"
            elif name == "click-mouse":
                enabled = visible_frame and self.motor.state["motor_execution"] == "free"
            elif name == "think":
                enabled = self.motor.manual_state == "free"
            elif name == "move-hand":
                enabled = self.motor.manual_state == "free"
            elif name == "press-key" or name.startswith("get-spelling-"):
                # The wrapper's frame NAME query also requires visibility
                # (frame-module-query, fixed2014 cogtool-actr.lisp 758-760).
                enabled = (visible_frame and self.motor.state["motor_preparation"] == "free" and
                           (not rule["execution_free"] or self.motor.state["motor_execution"] == "free"))
            elif name == "stop":
                enabled = True
            else:
                raise RuntimeError("compiled unknown rule")
            if enabled:
                candidates.append(dict(rule))
        return candidates

    def before_selection(self, chosen):
        self.step = self.step_map.get(chosen["step_index"])
        self.target = chosen["target"]
        self.state["current_target"] = self.target

    def location_search_available(self):
        # An already selected FIND is not re-matched against frame visibility.
        # system-wait-start only hides the frame query flag, not the visicon;
        # vision.lisp find-location:2429-2449 searches that existing visicon.
        return self.target in self.visible and self.target in self.locations

    def fire(self, selected):
        name = selected["name"]
        step = self.step_map.get(selected["step_index"])
        self.record("production_fired", rule=name, details={"selection": selected, "lhs_rechecked": False},
                    source_key="firing")
        if name == "set-start-frame":
            self.display()
            self.goal_update(goal_state=selected["state_to"])
        elif name in {"find", "find-location"}:
            self.goal_update(goal_state=selected["state_to"])
            self.clock.schedule(0, self.find_request, priority=50)
        elif name == "look-at":
            self.goal_update(goal_state=selected["state_to"], suppress_re_encoding=True)
            bound = deepcopy(selected["bound_location"])
            self.clock.schedule(0, lambda: self.attention_request(bound), priority=50)
        elif name == "*suppress-re-encoding":
            self.goal_update(suppress_re_encoding=False)
            self.clock.schedule(0, self.clear_visual, priority=50)
        elif name in {"move-mouse", "prepare-click", "click-mouse", "press-key", "move-hand"}:
            transition = self.transitions.get(step.index) if name in {"click-mouse", "press-key"} else None
            if name == "press-key":
                # set-cogtool-plist:264-285 increments on each actual request,
                # not once per string. Destination survives until consumed.
                self.state["pending_keystrokes"] += 1
                if transition:
                    if self.pending_keyboard_transition is not None:
                        self.unsupported("overlapping unconsumed keyboard destinations",step=step)
                        return
                    self.pending_keyboard_transition = step.index
                self.record("keyboard_request_registered",details={"step_index":step.index,
                    "key":step.key,"pending_keystrokes":self.state["pending_keystrokes"],
                    "transition_id":transition["annotation"].note if transition else None},source_key="device")
            if transition and transition["delay_s"] > 0:
                self.pending_waits.append(transition)
            self.goal_update(goal_state=selected["state_to"])
            bound = deepcopy(selected["bound_location"])
            self.clock.schedule(0, lambda: self.manual_request(name, step, bound), priority=50)
        elif name == "think" or name.startswith("get-spelling-"):
            self.goal_update(goal_state=selected["state_to"])
        elif name == "stop":
            self.model_stop = self.clock.now / 1000
            self.clock.schedule(0, lambda: self.changed("goal_stop", {"goal_state": "stop"}, "stop"), priority=50)
            self.record("model_stop", rule="stop", details={"halts_scheduler": False}, source_key="stop")
        self.state.update(procedural_busy=False, selected_rule=None)
        self.selected = None
        self.check_later()

    def attention_request(self, bound):
        if bound is None:
            self.unsupported("LOOK lacks selected location binding")
            return
        step = self.step
        request_event = self.record("visual_attention_request", details={"bound_location": bound, "completion": "computed_by_EMMA"},
                                    source_key="look")
        self.clock.schedule(0, self.clear_visual_buffer, priority=10)

        def request():
            request = self.vision.request(bound, (request_event["event_id"],))
            self.vision_context[request["request_id"]] = step
            if self.vision.unsupported_reason:
                self.unsupported(self.vision.unsupported_reason)
        self.clock.schedule(0, request, priority=0)
        self.clock.schedule(0, lambda: self.changed("visual_request_unlock", {"device_locked": False}, "lock"), priority=":min")

    def observe_vision(self, module, change):
        updates = {key: deepcopy(value) for key, value in module.state.items()
                   if key.startswith("visual_")}
        updates["visual_completion_unmodeled"] = False
        updates["visual_last_confirmed_at_s"] = self.clock.now / 1000
        event = self.changed("visual_state_update", updates, "look", details={"vision_change": deepcopy(change)})
        request_id = change.get("request_id")
        step = self.vision_context.get(request_id, self.step) if request_id is not None else None
        event.update(step_index=step.index if step else None,
                     demo_index=step.demo_index if step else None,
                     target=step.target if step else None)
        if module.unsupported_reason:
            self.unsupported(module.unsupported_reason)

    def clear_visual(self):
        # Implicit clear-buffer priority 10 and module clear priority 0 are
        # distinct effects of a +visual request, as for move-attention.
        self.record("visual_clear_request", source_key="start")
        self.clock.schedule(0, self.clear_visual_buffer, priority=10)
        def clear():
            self.vision.clear()
            if self.vision.unsupported_reason:
                self.unsupported(self.vision.unsupported_reason)
        self.clock.schedule(0, clear, priority=0)
        self.clock.schedule(0, lambda: self.changed("visual_request_unlock", {"device_locked": False}, "lock"), priority=":min")

    def clear_visual_buffer(self):
        values = {"visual_content": None, "visual_object": None, "visual_requested": False}
        self.vision.state.update(values)
        self.changed("visual_buffer_clear", values, "look")

    def manual_request(self, name, step, bound):
        event = self.record("mouse_request" if name == "move-mouse" else "manual_request", rule=name,
                            details={"bound_location": bound, "step_index": step.index},
                            source_key="move" if name == "move-mouse" else "click")
        event.update(target=step.target, step_index=step.index, demo_index=step.demo_index)
        if name == "move-mouse":
            if bound is None or bound["target"] != step.target:
                self.unsupported("MOVE target binding differs from supported step", step=step)
                return
            if self.first_mouse_request is None:
                self.first_mouse_request = self.clock.now / 1000
            if self.motor.manual_state != "free":
                self.unsupported("MOVE requires unimplemented manual queue after selection", step=step)
                return
        if name == "prepare-click":
            if self.motor.state["motor_preparation"] != "free":
                self.unsupported("selected prepare would jam", step=step)
                return
            self.motor.prepare(step, (event["event_id"],), on_state_change=self.observe_motor)
            return
        if self.motor.active_request is not None and not self.motor.keyboard_enabled:
            self.unsupported("overlapping queued motor execution outside integrated scope", step=step)
            return
        if step.index in self.issued_steps:
            raise RuntimeError("same generated device command issued twice")
        self.issued_steps.add(step.index)
        self.motor.request(step, (event["event_id"],), on_state_change=self.observe_motor)

    def observe_motor(self, module, change):
        update = self.record("manual_state_update", details={"motor_change": deepcopy(change)}, source_key="move")
        event_id = change["event_id"]
        event = next((e for e in module.events if e["event_id"] == event_id), None)
        if event:
            update.update(target=event["target"], step_index=event["step_index"], demo_index=event["demo_index"])
        if event and change["trigger"] in {"cursor_move", "cursor_noop", "click_output", "key_output", "hand_move", "hand_noop"}:
            self.completed_device_steps.add(event["step_index"])
        if event and change["trigger"] == "click_output":
            step = self.step_map[event["step_index"]]
            if step.op == "right_click":
                if self.first_right_click is None:
                    self.first_right_click = self.clock.now / 1000
                self.state["menu_open"] = True
                opened = self.record("menu_open", details={"device_event_id": event_id, "target": step.target,
                            "interpretation": "demonstrated right-button semantics; upstream physical command is click-mouse/punch"},
                            source_key="device")
                opened.update(target=step.target, step_index=step.index, demo_index=step.demo_index)
            elif self.frame.widget(step.target, "click output").kind == "menu_item":
                self.state["menu_open"] = False
                self.menu_selection = self.clock.now / 1000
                selected = self.record("menu_selection", details={"device_event_id": event_id, "target": step.target},
                            source_key="device")
                selected.update(target=step.target, step_index=step.index, demo_index=step.demo_index)
            if step.index in self.transitions:
                self.device_transition(step, event_id)
        if event and change["trigger"] == "key_output":
            step = self.step_map[event["step_index"]]
            self.state["pending_keystrokes"] -= 1
            if self.state["pending_keystrokes"] < 0:
                raise RuntimeError("key output without an issued key production")
            self.record("keyboard_output_registered",details={"step_index":step.index,"key":step.key,
                "pending_keystrokes":self.state["pending_keystrokes"],"device_event_id":event_id},source_key="device")
            segment = [s for s in self.script.steps if s.demo_index==step.demo_index and s.op=="key"]
            if step.index == segment[-1].index:
                demo = self.task.demonstration.steps[step.demo_index]
                self.record("keyboard_action_complete",details={"demo_index":step.demo_index,
                    "keys":list(demo.keys),"is_command":demo.is_command,"modifiers":demo.modifiers,
                    "device_id":demo.device_id,"step_index":step.index,"device_event_id":event_id},source_key="device")
            if self.state["pending_keystrokes"] == 0 and self.pending_keyboard_transition is not None:
                owner = self.step_map[self.pending_keyboard_transition]
                self.pending_keyboard_transition = None
                self.device_transition(owner, event_id)
        self.check_later()

    def display(self):
        # A frame name is a device state, not a new clock, mouse or eye state.
        super().display()
        for location in self.locations.values():
            location["frame"] = self.frame.id

    def device_transition(self, step, event_id):
        transition = self.transitions[step.index]
        destination = transition["destination"]
        if destination != self.frame.id:
            self.activate_frame(destination, event_id, step)
        else:
            self.record("same_frame_transition_noop", details={"step_index":transition["annotation"].index,
                        "device_event_id":event_id,"scene_reset":False},source_key="device")
        self.start_pending_wait()

    def activate_frame(self, destination, event_id, step):
        old_frame = self.frame.id
        self.frame = self.project.design.frame(destination, "device transition")
        self.locations = {w.id:{"chunk_id":f"location:{destination}:{w.id}","target":w.id,
                          "value":w.name+" in "+self.frame.name,"frame":destination,
                          "x":w.center[0],"y":w.center[1],"kind":"widget",
                          "creation_time_s":self.clock.now/1000} for w in self.frame.widgets}
        for a in self.config.auxiliary_locations:
            if a.frame == destination:
                self.locations[a.id]={"chunk_id":f"location:{destination}:{a.id}","target":a.id,
                    "value":a.id,"frame":destination,"x":a.x,"y":a.y,"kind":"group",
                    "creation_time_s":self.clock.now/1000}
        self.visible=set(self.locations)
        self.motor.state["frame"]=destination
        self.state.update(current_frame=destination,scene_locations=sorted(self.visible))
        self.record("frame_transition",details={"from_frame":old_frame,"to_frame":destination,
                    "device_event_id":event_id,"trigger_step_index":step.index,
                    "mouse_and_eye_preserved":True},source_key="device")
        # process-display updates visicon; a copied visual-location buffer is
        # not automatically cleared (vision.lisp624-753,891-910). General
        # disappearance during an unfinished attention shift stays a boundary.
        if self.vision.state["attended_target"] is not None or self.vision.state["moving_attention"] is not None:
            self.unsupported("frame change with attended/pending visual object needs dynamic EMMA re-encoding",step=step)
            return
        self.record("proc_display",details={"locations":list(self.locations.values()),
                    "old_visual_location_buffer_preserved":True},source_key="initialization")
        if self.config.auto_stuffing:
            self.stuff()

    def start_pending_wait(self):
        # cogtool-actr.lisp1052-1081: triggered after device transition, FIFO;
        # hide the frame flag without a new proc-display at wait start.
        if self.wait_active or not self.pending_waits:
            return
        wait=self.pending_waits.pop(0);self.wait_active=True
        self.state["frame_visible"]=False
        self.record("system_wait_start",details={"duration_s":wait["delay_s"],
                    "delay_label":wait["delay_label"],
                    "annotation_index":wait["annotation"].index,"frame":self.frame.id},source_key="device")
        def finish():
            self.wait_active=False
            self.record("system_wait_end",details={"frame":self.frame.id,"delay_label":wait["delay_label"]},source_key="device")
            if self.pending_waits:
                self.start_pending_wait()
            else:
                self.state["frame_visible"]=True
                self.record("proc_display",details={"locations":list(self.locations.values()),
                            "reason":"system_wait_complete"},source_key="initialization")
                if self.config.auto_stuffing:
                    self.stuff()
            self.check_later()
        self.clock.schedule(wait["delay_s"],finish,priority=":max")

    def run(self):
        if len({f.name for f in self.project.design.frames}) != len(self.project.design.frames):
            self.unsupported("ambiguous duplicate frame names in source name-keyed device")
        for frame in self.project.design.frames:
            values = [w.name + " in " + frame.name for w in frame.widgets]
            values += [a.id for a in self.config.auxiliary_locations if a.frame == frame.id]
            if len(set(values)) != len(values):
                self.unsupported("ambiguous duplicate visual values in frame " + frame.id)
        if len({v["value"] for v in self.locations.values()}) != len(self.locations):
            self.unsupported("ambiguous duplicate visual values")
        self.record("initial_state", details={"profile": self.config.profile, "provenance": self.config.provenance,
                    "scope": "integrated_task", "artificial_completion_events": False}, source_key="initialization")
        self.record("compiled_productions", details={"rules": deepcopy(self.rules),
                    "script_generation_count": 1, "source_of_steps": "current Python bounded generator; not cached 2009 steps"},
                    source_key="writer")
        if not self.failure:
            if self.config.profile == "source_2014_defaults":
                # cogtool-run-model processes the still-empty device before
                # run/START. build-vis-locs-for calls the real module clear;
                # its pending preparation release can affect first selection.
                # Synthetic profiles explicitly start after this initialization.
                startup = self.record("startup_empty_proc_display", details={"current_frame": None,
                            "synchronous_before_run": True, "module_call": "visual clear"},
                            source_key="startup_clear")
                startup.update(step_index=None, demo_index=None, target=None)
                self.vision.clear()
            elif self.config.auto_stuffing:
                self.clock.schedule(0, self.stuff, priority=10)
            self.check_later()
            self.drain_bounded()
        required = {s.index for s in self.script.steps if s.op in {"point", "click", "right_click", "key", "home"}}
        if self.failure:
            status = self.failure if self.failure in {"time_limit", "event_limit"} else "partial"
            reason = self.failure
        elif (self.model_stop is not None and not self.clock.queue and
              not self.vision.has_pending_events and required == self.completed_device_steps and
              self.motor.active_request is None and
              self.state["pending_keystrokes"] == 0 and self.pending_keyboard_transition is None and
              not self.wait_active and not self.pending_waits and
              self.state["current_frame"] == self.script.final_state["frame"] and
              all(request["completed"] for request in self.vision.requests) and
              self.motor.manual_state == "free" and self.visual_free()):
            status, reason = "complete", "event_queue_exhausted_after_stop"
        else:
            status, reason = "partial", "waiting_or_deadlock_without_complete_task"
            self.blocker = self.blocker or {"reason": reason, "goal_state": self.state["goal_state"],
                        "missing_device_steps": sorted(required - self.completed_device_steps)}
        self.termination_reason = reason
        self.record("task_boundary", details={"completion_status": status, "termination_reason": reason,
                    "pending_events": len(self.clock.queue), "full_task_completed": status == "complete",
                    "blocker": self.blocker}, source_key="termination")
        return status

    def result_fields(self, status):
        total = self.clock.now / 1000 if status == "complete" else None
        visual_free_times = [record["time_s"] for record in self.vision.state_changes
                             if all(record["after"][key] == "free" for key in
                                    ("visual_preparation", "visual_processor", "visual_execution"))]
        return {
            "execution_scope": "integrated_task", "runtime_policy": {**deepcopy(POLICY),
                "scope": "bounded frame-local scenes; EMMA explicit/automatic LookAt, Text click, alphanumeric/DOWN KeyAction, owned keyboard transitions, Home, response and STOP",
                "run_policy": self.config.run_policy, "simulation_limit_s": self.config.max_time_s,
                "event_limit": self.config.max_events,
                "wall_clock_timeout_s": None, "wall_clock_timeout_scope": "external launcher policy; not a model parameter",
                "randomize_time": False, "eye_noise": "CogTool override returns mean", "source_seed": [1, 0]},
            "predicted_time_s": total, "reported_task_time_s": total,
            "model_stop_time_s": self.model_stop, "task_stop_time_s": self.model_stop,
            "simulation_end_time_s": self.clock.now / 1000, "elapsed_simulation_s": self.clock.now / 1000,
            "last_visual_release_time_s": max(visual_free_times) if visual_free_times else None,
            "first_right_click_output_time_s": self.first_right_click,
            "menu_selection_time_s": self.menu_selection,
            "termination_reason": self.termination_reason, "blocker": self.blocker,
            "vision_events": deepcopy(self.vision.events), "vision_state_changes": deepcopy(self.vision.state_changes),
            "vision_requests": deepcopy(self.vision.requests),
            "compiled_productions": deepcopy(self.rules),
            "remaining_unsupported_mechanisms": [] if status == "complete" else [self.blocker or self.termination_reason],
            "unsupported_outside_scope": ["ambiguous locations or frame changes during attended/pending visual encoding",
                                          "visual overlap outside explicit module support", "modifiers/function keys other than DOWN/non-ASCII text and application command interpretation",
                                          "standalone wait, child-widget LookAt, nested/hover/doubleclick or repeated same-parent menu"],
            "timing_boundary": "source run first return: simulated elapsed time at event exhaustion after goal STOP; no keep-alive or periodic events",
            "scope": ["same experimental engine, integrated_task range", "one bounded demonstration expansion",
                      "known-target strings, bounded full frame transitions and FIFO system response on device output",
                      "preserved shared motor module and source-priority clock"],
            "validation": {"original_comparison": "unverified", "claim": "complete bounded 2014-source diagnostic execution" if status == "complete" else "partial integrated execution"},
            "warnings": ["No new original runtime result or human prediction validation.",
                         "2009 initial conditions and version equivalence remain unknown.",
                         "Right versus left button is task-semantic annotation; upstream uses the same punch/click-mouse command."],
        }
