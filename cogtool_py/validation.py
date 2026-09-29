"""Validate actual model objects without serialization or script generation.

Validation follows only the declared demonstration's frame/focus path. It does
not insert operators, estimate time, or infer a user's method.
"""
from __future__ import annotations

from dataclasses import fields
from typing import Any

from .models import (
    Demonstration, DemonstrationStep, Design, Frame, InitialState, ModelError,
    ParameterSet, Project, SUPPORTED_KEYS, Task, Transition, Widget, InputDevice,
    ENGINE_NAMES, MOTOR_ENGINE, MOTOR_DEFAULTS, CONTROL_ENGINE, CONTROL_DEFAULTS, VISION_DEFAULTS, KEYBOARD_DEFAULTS,
    choice, fail, finite_coordinate, number, string,
)


def _instance(value: Any, expected: type, path: str) -> None:
    if type(value) is not expected:
        extra = "; expanded ScriptStep is not a demonstration" if expected is DemonstrationStep else ""
        fail(path, f"expected {expected.__name__}, received {type(value).__name__}{extra}")
    for field in fields(expected):
        if not hasattr(value, field.name):
            fail(path + "." + field.name, "required field is missing")


def _tuple(value: Any, path: str, *, nonempty: bool = True) -> None:
    if type(value) is not tuple or (nonempty and not value):
        fail(path, "expected a nonempty tuple" if nonempty else "expected a tuple")


def _duration(value: Any, path: str) -> None:
    try:
        number(value, path)
    except ModelError:
        fail(path, "computed time is out of range; expected a finite nonnegative duration in seconds")


def validate_mouse(mouse: Any, path: str = "point.mouse") -> None:
    if type(mouse) not in (tuple, list) or len(mouse) != 2:
        fail(path, "expected exactly two coordinates [x, y] in px")
    for index, value in enumerate(mouse):
        finite_coordinate(value, f"{path}[{index}]")


def validate_parameters(parameters: Any, path: str = "parameters") -> None:
    _instance(parameters, ParameterSet, path)
    parameters.validate(path=path)


def validate_widget(widget: Any, path: str = "point.widget") -> None:
    _instance(widget, Widget, path)
    string(widget.id, path + ".id")
    string(widget.name, path + ".name")
    string(widget.label, path + ".label", empty=True)
    choice(widget.kind, path + ".kind", {"button", "link", "textbox", "text", "context_menu", "menu_item"})
    finite_coordinate(widget.x, path + ".x")
    finite_coordinate(widget.y, path + ".y")
    number(widget.width, path + ".width", positive=True)
    number(widget.height, path + ".height", positive=True)
    if widget.kind == "menu_item":
        string(widget.parent, path + ".parent")
    elif widget.parent is not None:
        fail(path + ".parent", "only single-level menu_item may have a parent")
    # Finite fields can still overflow when the target center is constructed.
    for index, value in enumerate(widget.center):
        finite_coordinate(value, f"{path}.center[{index}]")


def _unique_ids(items: tuple, path: str) -> None:
    seen: set[str] = set()
    for i, item in enumerate(items):
        if item.id in seen:
            fail(f"{path}[{i}].id", f"duplicate id {item.id!r}")
        seen.add(item.id)


def _widget(frame: Frame, ident: str, path: str) -> Widget:
    for widget in frame.widgets:
        if widget.id == ident:
            return widget
    fail(path, f"widget {ident!r} does not exist in frame {frame.id!r}")


def _validate_step(step: Any, path: str) -> None:
    _instance(step, DemonstrationStep, path)
    choice(step.op, path + ".op", {"point", "click", "keys", "home", "think", "look_at", "wait", "menu_select"})
    if type(step.is_command) is not bool:
        fail(path + ".is_command", "expected boolean, not a modifier key")
    if type(step.modifiers) is not int or step.modifiers != 0:
        fail(path + ".modifiers", "only zero modifiers supported; no implicit chord expansion")
    if step.op != "keys" and (step.is_command or step.device_id is not None or step.key_text is not None):
        fail(path, "is_command/device_id require a keys action")
    if step.device_id is not None:
        string(step.device_id, path + ".device_id")
        if step.device != "keyboard":
            fail(path + ".device", "device_id requires the keyboard role")
    if step.op in {"point", "click", "look_at", "menu_select"}:
        string(step.target, path + ".target")
    elif step.target is not None:
        fail(path + ".target", f"field is not supported for {step.op}")
    _tuple(step.keys, path + ".keys", nonempty=step.op == "keys")
    if step.key_text is not None:
        _validate_key_text(step.key_text, step.keys, path + ".key_text")
    if step.op == "keys":
        for index, key in enumerate(step.keys):
            choice(key, f"{path}.keys[{index}] (IME/shift/chords unsupported)", SUPPORTED_KEYS)
    elif step.keys:
        fail(path + ".keys", f"field is not supported for {step.op}")
    if step.op == "wait" or (step.op in {"look_at", "think"} and step.duration_s is not None):
        _duration(step.duration_s, path + ".duration_s")
    elif step.duration_s is not None:
        fail(path + ".duration_s", f"field is not supported for {step.op}")
    if step.op == "home":
        choice(step.device, path + ".device", {"mouse", "keyboard"})
    elif step.op == "keys" and step.device is not None:
        choice(step.device, path + ".device", {"keyboard"})
    elif step.device is not None:
        fail(path + ".device", f"field is not supported for {step.op}")
    if step.transition is not None:
        if step.op not in {"click", "menu_select", "keys"}:
            fail(path + ".transition", f"field is not supported for {step.op}")
        string(step.transition, path + ".transition")


def _validate_key_text(text, keys, path):
    string(text, path)
    # Persistence encoding from KeyboardUtil.DOWN_ARROW_CHAR. It can be kept
    # on an unexecuted graph edge without claiming integrated key support.
    encoded = "".join("\ue00d" if key == "DOWN" else key for key in keys if isinstance(key,str))
    if text != encoded:
        fail(path, "raw KeyAction text disagrees with the declared physical key sequence")


def _validate_task(task: Task, frames: dict[str, Frame], transitions: dict[tuple[str, str], Transition],
                   device_transitions: tuple[Transition, ...] = (),
                   *, allow_distinct_menus: bool = False, allow_keyboard_device: bool = False,
                   allow_source_look: bool = False) -> None:
    path = f"task[{task.id}]"
    _instance(task.demonstration, Demonstration, path + ".demonstration")
    demonstration = task.demonstration
    initial_path = path + ".initial"
    _instance(demonstration.initial, InitialState, initial_path)
    initial = demonstration.initial
    string(initial.frame, initial_path + ".frame")
    if initial.frame not in frames:
        fail(initial_path + ".frame", f"frame {initial.frame!r} does not exist")
    validate_mouse(initial.mouse, initial_path + ".mouse")
    choice(initial.mouse_hand, initial_path + ".mouse_hand", {"right", "left"})
    choice(initial.hand, initial_path + ".hand", {"mouse", "keyboard"})
    frame = frames[initial.frame]
    focus = initial.focus
    if focus is not None:
        string(focus, initial_path + ".focus")
        if _widget(frame, focus, initial_path + ".focus").kind != "textbox":
            fail(initial_path + ".focus", "focus must be a textbox")
    _tuple(demonstration.steps, path + ".steps")
    menu_selected = False
    seen_menu_parents = set()
    continuous_menus = all(isinstance(step, DemonstrationStep) and step.op == "menu_select"
                           for step in demonstration.steps)
    for index, step in enumerate(demonstration.steps):
        step_path = f"{path}.steps[{index}]"
        _validate_step(step, step_path)
        target = _widget(frame, step.target, step_path + ".target") if step.target is not None else None
        if step.op == "look_at":
            if allow_source_look:
                if step.duration_s is not None:
                    fail(step_path + ".duration_s", "source LookAt has no fixed duration; omit duration_s to use the real VisionModule")
                if target.kind not in {"text", "button", "textbox", "link"}:
                    fail(step_path + ".target", "source LookAt currently supports ordinary widgets; child/menu opening semantics are outside scope")
            elif step.duration_s is None:
                fail(step_path + ".duration_s", "missing duration_s for baseline LookAt; source LookAt requires integrated_task")
        if step.op == "menu_select":
            if target.kind != "menu_item":
                fail(step_path + ".target", "menu_select requires a menu_item with a context_menu parent")
            if menu_selected:
                if not allow_distinct_menus or not continuous_menus:
                    fail(step_path + ".op", "unsupported repeated menu selection; multiple menus require integrated_task and consecutive menu_select actions")
                if (frame.id, target.parent) in seen_menu_parents:
                    fail(step_path + ".op", "unsupported repeated menu selection from the same parent; upstream isOpen would change generated actions")
            if allow_distinct_menus and continuous_menus and len(demonstration.steps) > 1:
                transition = transitions.get((frame.id, target.id))
                if frame.id != initial.frame or (transition is not None and
                        (transition.to_frame != frame.id or transition.delay_s != 0)):
                    fail(step_path + ".transition", "multiple menu selections require one frame and zero-delay self transitions")
            seen_menu_parents.add((frame.id, target.parent))
            menu_selected = True
        elif target is not None and (target.kind == "menu_item" or (step.op == "click" and target.kind == "context_menu")):
            fail(step_path + ".target", "menu targets require menu_select; direct click/hidden-item operations are unsupported")
        if step.op in {"click", "menu_select"}:
            transition = transitions.get((frame.id, target.id))
            if transition is not None and step.transition != transition.id:
                fail(step_path + ".transition", f"click requires explicitly selected transition {transition.id!r}")
            if transition is None and step.transition is not None:
                fail(step_path + ".transition", f"transition {step.transition!r} is not defined for this frame/widget")
            focus = target.id if target.kind == "textbox" else None
            if transition is not None:
                if transition.to_frame != frame.id:
                    focus = None
                frame = frames[transition.to_frame]
        elif step.op == "keys":
            if step.device == "keyboard":
                if not allow_keyboard_device:
                    fail(step_path + ".device", "global keyboard device input requires integrated_task scope")
                if step.device_id is not None:
                    frame.device(step.device_id, step_path + ".device_id")
                elif step.transition is not None:
                    fail(step_path + ".device_id", "keyboard transition requires an explicit frame-owned device")
                matches = [t for t in device_transitions if t.from_frame == frame.id and
                           t.source_id == step.device_id and t.keys == step.keys and
                           t.is_command == step.is_command and t.modifiers == step.modifiers]
                transition = matches[0] if matches else None
                if transition is not None and step.transition != transition.id:
                    fail(step_path + ".transition", f"keys requires explicitly selected transition {transition.id!r}")
                if transition is None and step.transition is not None:
                    fail(step_path + ".transition", "no matching input-device transition for frame, device and full KeyAction")
                if transition is not None:
                    if frame.id != transition.to_frame:focus = None
                    frame = frames[transition.to_frame]
                continue
            if step.is_command or step.transition is not None:
                fail(step_path, "command actions/transitions require explicit keyboard device input in integrated_task")
            if focus is None:
                fail(step_path + ".keys", "keyboard input requires initial focus or a prior textbox click")
            if _widget(frame, focus, step_path + ".keys.focus").kind != "textbox":
                fail(step_path + ".keys.focus", "keyboard focus is not a textbox")


def validate_project(project: Any) -> None:
    """Validate a Project's actual fields and declared path without expanding it."""
    _instance(project, Project, "project")
    if type(project.schema_version) is not int or project.schema_version not in {1, 2}:
        fail("schema_version", "only integer schema versions 1 and 2 are supported")
    string(project.id, "project.id")
    string(project.name, "project.name")
    choice(project.engine, "engine (no automatic fallback)", ENGINE_NAMES)
    validate_parameters(project.parameters)
    if project.parameters.entries.keys() & KEYBOARD_DEFAULTS.keys() and not (
            project.engine == CONTROL_ENGINE and project.control is not None and
            project.control.execution_scope == "integrated_task"):
        fail("parameters", "keyboard motor parameters require integrated_task scope")
    if project.engine in {MOTOR_ENGINE, CONTROL_ENGINE} and not MOTOR_DEFAULTS.keys() <= project.parameters.entries.keys():
        fail("parameters", "experimental motor engine requires an explicit complete motor profile; use with_motor_defaults() and save it")
    if project.engine == "klm_baseline" and project.parameters.entries.keys() & MOTOR_DEFAULTS.keys():
        fail("parameters", "motor subset parameters require the experimental engine")
    if project.engine == CONTROL_ENGINE:
        if not CONTROL_DEFAULTS.keys() <= project.parameters.entries.keys():
            fail("parameters", "control prefix requires explicit parameters; use with_control_defaults()")
        from .control_models import validate_control
        validate_control(project.control)
        if project.control.execution_scope == "integrated_task":
            if not VISION_DEFAULTS.keys() <= project.parameters.entries.keys():
                fail("parameters", "integrated task requires explicit vision profile; use with_vision_defaults()")
        elif project.parameters.entries.keys() & VISION_DEFAULTS.keys():
            fail("parameters", "vision parameters require integrated_task scope")
    elif project.control is not None or project.parameters.entries.keys() & CONTROL_DEFAULTS.keys():
        fail("control", "control state/parameters require the explicit control prefix engine")
    if project.engine != CONTROL_ENGINE and project.parameters.entries.keys() & VISION_DEFAULTS.keys():
        fail("parameters", "vision parameters require the control experimental engine")
    design = project.design
    _instance(design, Design, "design")
    string(design.id, "design.id")
    string(design.name, "design.name")
    choice(design.coordinate_unit, "design.coordinate_unit", {"px"})
    _tuple(design.frames, "design.frames")
    for i, frame in enumerate(design.frames):
        path = f"design.frames[{i}]"
        _instance(frame, Frame, path)
        string(frame.id, path + ".id")
        string(frame.name, path + ".name")
        _tuple(frame.widgets, path + ".widgets", nonempty=False)
        _tuple(frame.devices, path + ".devices", nonempty=False)
        for j, device in enumerate(frame.devices):
            dp = f"{path}.devices[{j}]"
            _instance(device, InputDevice, dp)
            string(device.id, dp + ".id");string(device.name, dp + ".name")
            choice(device.kind, dp + ".kind", {"keyboard"})
        _unique_ids(frame.devices, path + ".devices")
        if len({d.kind for d in frame.devices}) != len(frame.devices):
            fail(path + ".devices", "only one source device per kind in each frame")
        for j, widget in enumerate(frame.widgets):
            validate_widget(widget, f"{path}.widgets[{j}]")
        _unique_ids(frame.widgets, path + ".widgets")
        for j, widget in enumerate(frame.widgets):
            if widget.kind == "menu_item":
                parent_path = f"{path}.widgets[{j}].parent"
                parent = _widget(frame, widget.parent, parent_path)
                if parent.kind != "context_menu":
                    fail(parent_path, "only a context_menu in the same frame may parent a menu_item; nested menus are unsupported")
    _unique_ids(design.frames, "design.frames")
    frames = {frame.id: frame for frame in design.frames}
    _tuple(design.transitions, "design.transitions", nonempty=False)
    triggers: dict[tuple[str, str], Transition] = {}
    device_transitions = []
    device_triggers = set()
    for i, transition in enumerate(design.transitions):
        path = f"design.transitions[{i}]"
        _instance(transition, Transition, path)
        for name in ("id", "from_frame", "to_frame"):
            string(getattr(transition, name), path + "." + name)
        _duration(transition.delay_s, path + ".delay_s")
        if transition.delay_label is not None:
            string(transition.delay_label, path + ".delay_label", empty=True)
        for name in ("from_frame", "to_frame"):
            if getattr(transition, name) not in frames:
                fail(path + "." + name, f"frame {getattr(transition, name)!r} does not exist")
        choice(transition.source_type, path + ".source_type", {"widget", "input_device"})
        if type(transition.is_command) is not bool:
            fail(path + ".is_command", "expected boolean")
        if type(transition.modifiers) is not int or transition.modifiers != 0:
            fail(path + ".modifiers", "only zero modifiers supported")
        _tuple(transition.keys, path + ".keys", nonempty=transition.source_type == "input_device")
        if transition.source_type == "input_device":
            if transition.target is not None:
                fail(path + ".target", "InputDevice is not a Widget; use source_id")
            string(transition.source_id, path + ".source_id")
            frames[transition.from_frame].device(transition.source_id, path + ".source_id")
            for j,key in enumerate(transition.keys):
                choice(key, f"{path}.keys[{j}]", SUPPORTED_KEYS)
            if transition.key_text is not None:
                _validate_key_text(transition.key_text, transition.keys, path + ".key_text")
            trigger = (transition.from_frame, transition.source_id, transition.keys,
                       transition.is_command, transition.modifiers)
            if trigger in device_triggers:fail(path, "ambiguous input-device transition for full KeyAction")
            device_triggers.add(trigger);device_transitions.append(transition)
            continue
        if transition.source_id is not None or transition.keys or transition.is_command or transition.key_text is not None:
            fail(path, "Widget transition cannot carry InputDevice source/action fields")
        string(transition.target, path + ".target")
        target = _widget(frames[transition.from_frame], transition.target, path + ".target")
        if target.kind == "context_menu":
            fail(path + ".target", "context_menu opening cannot trigger a page transition; select an item")
        trigger = (transition.from_frame, transition.target)
        if trigger in triggers:
            fail(path, "ambiguous click transition for frame/widget")
        triggers[trigger] = transition
    _unique_ids(design.transitions, "design.transitions")
    _tuple(project.tasks, "tasks")
    for i, task in enumerate(project.tasks):
        _instance(task, Task, f"tasks[{i}]")
        string(task.id, f"tasks[{i}].id")
        string(task.name, f"task[{task.id}].name")
    _unique_ids(project.tasks, "tasks")
    for task in project.tasks:
        _validate_task(task, frames, triggers, tuple(device_transitions),
                       allow_distinct_menus=project.engine == CONTROL_ENGINE and
                       project.control.execution_scope == "integrated_task",
                       allow_keyboard_device=project.engine == CONTROL_ENGINE and
                       project.control.execution_scope == "integrated_task",
                       allow_source_look=project.engine == CONTROL_ENGINE and
                       project.control.execution_scope == "integrated_task")
    if project.engine == CONTROL_ENGINE:
        from .control_models import validate_control_references
        validate_control_references(project)


def validate_selected_task(project: Project, task: Any) -> None:
    """Called after validate_project by the public script-generation boundary."""
    _instance(task, Task, "task")
    if not any(task is candidate for candidate in project.tasks):
        fail("task", "selected Task must be one of the validated Project.tasks objects")
