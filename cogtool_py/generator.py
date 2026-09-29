"""Restricted translation of CogTool's KLM rules, not its ACT-R writer.

Derived rules: CMU CogTool 1.3 (2005–2013), LGPL-2.1-or-later.
Python changes dated 2026-09-24; see NOTICE.md and inline source references.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import GENERATOR, source
from .models import COMMAND_KEYS, LEFT_KEYS, CONTROL_ENGINE, Project, Task, Widget, fail
from .validation import validate_project, validate_selected_task


def rule(symbol: str) -> str:
    return source(GENERATOR, symbol)


@dataclass(frozen=True)
class ScriptStep:
    index: int
    op: str
    origin: str
    demo_index: int
    frame: str
    target: str | None
    key: str | None
    duration_s: float | None
    device: str | None
    source: str
    note: str
    state_before: dict[str, Any]
    state_after: dict[str, Any]


@dataclass(frozen=True)
class GeneratedScript:
    steps: tuple[ScriptStep, ...]
    warnings: tuple[str, ...]
    final_state: dict[str, Any]


def identical(a: Widget | None, b: Widget) -> bool:
    """KLMCognitiveGenerator.isIdentical:1435; frame/id are not compared."""
    return a is not None and (a.name, a.label, a.kind, a.bounds) == (b.name, b.label, b.kind, b.bounds)


def terminator(w: Widget | None, names: set[str]) -> bool:
    return w is not None and (w.name.lower() in names or w.label.lower() in names)


def generate(project: Project, task: Task) -> GeneratedScript:
    validate_project(project)
    validate_selected_task(project, task)
    return _generate_validated(project, task)


def _generate_validated(project: Project, task: Task) -> GeneratedScript:
    """Internal expansion after actual-object validation; never a parser."""
    initial = task.demonstration.initial
    state: dict[str, Any] = {"frame": initial.frame, "mouse": list(initial.mouse),
                             "mouse_hand": initial.mouse_hand, "hand": initial.hand,
                             "focus": initial.focus, "look_target": None}
    steps: list[ScriptStep] = []
    warnings: list[str] = []
    last_clicked: Widget | None = None
    last_moved: Widget | None = None
    fsm = "initial"
    last_cmd: str | None = None
    last_mental = False
    last_explicit_look: Widget | None = None
    source_look = project.engine == CONTROL_ENGINE and project.control.execution_scope == "integrated_task"
    demo_index = 0

    def emit(op: str, origin: str, src: str, *, target: str | None = None,
             key: str | None = None, duration: float | None = None,
             device: str | None = None, update: dict | None = None, note: str = "") -> None:
        nonlocal last_mental
        before = dict(state)
        if update:
            state.update(update)
        steps.append(ScriptStep(len(steps), op, origin, demo_index, before["frame"], target,
                                key, duration, device, src, note, before, dict(state)))
        last_mental = op in {"think", "look_at"}

    def mental() -> None:
        if not last_mental:
            emit("think", "automatic", rule("addMental:616-630;handleMouseTap:1616-1650;handleKeyInput:815-883"),
                 duration=project.parameters.value("think_s"))

    def home(device: str, origin: str = "automatic") -> None:
        if state["hand"] != device:
            emit("home", origin, rule("addHome:636-656;addHomeMouse:659;addHomeKeyboard:673"),
                 device=device, update={"hand": device})
        elif origin == "demonstrated":
            emit("home", origin, "cogtool_py:explicit redundant home recorded as zero-time no-op",
                 duration=0.0, device=device, note="already on requested device")

    for demo_index, demo in enumerate(task.demonstration.steps):
        path = f"task[{task.id}].steps[{demo_index}]"
        frame = project.design.frame(state["frame"], path)
        widget = frame.widget(demo.target, path + ".target") if demo.target else None
        if demo.op == "menu_select":
            # Each admitted parent is initially closed. Integrated scope also
            # admits consecutive distinct parents: isOpen follows lastClicked's
            # parent chain (upstream1023-1038) and is false for the new parent.
            # Same-parent repetition remains rejected; no state is reset here.
            parent = frame.widget(widget.parent, path + ".target.parent")
            home("mouse")
            if last_moved is None or last_moved.bounds != parent.bounds:
                emit("point", "automatic", rule("produceMenuSteps:1169-1173;addMoveMouse:683-710"),
                     target=parent.id, update={"mouse": list(parent.center)})
                last_moved = parent
            emit("right_click", "automatic", rule("produceMenuSteps:1110-1141,1184-1190"),
                 target=parent.id, update={"focus": None},
                 note="open initially closed context menu; explicit click_s baseline block, not ACT-R timing")
            last_clicked = parent
            mental()
            if last_moved.bounds != widget.bounds:
                emit("point", "automatic", rule("produceItemSteps:1210-1222;addAutoStep:988-1015"),
                     target=widget.id, update={"mouse": list(widget.center)})
                last_moved = widget
            emit("click", "demonstrated", rule("produceItemSteps:1210-1222"), target=widget.id,
                 update={"focus": None}, note="menu_select chooses a specified item; no visual search inferred")
            last_clicked = widget
            fsm = "menu_item"
            transition = next((t for t in project.design.transitions
                               if t.from_frame == frame.id and t.target == widget.id), None)
            if transition is not None:
                if transition.delay_s:
                    emit("wait", "automatic", rule("handleTransitionDelay:1761-1778"), duration=transition.delay_s,
                         note="serial baseline barrier starts after item click; no overlap")
                changed = transition.to_frame != frame.id
                emit("transition", "automatic", "cogtool_py:serial transition commit after response barrier", duration=0.0,
                     update={"frame": transition.to_frame, "focus": None,
                             "look_target": None if changed else state["look_target"]}, note=transition.id)
            warnings.append(path + ": single initially closed context menu, known target only; right_click uses explicit click_s; no general menu state or ACT-R equivalence")
        elif demo.op in {"point", "click"}:
            assert widget is not None
            if demo.op == "click":
                if widget.kind in {"button", "link"}:
                    if fsm != "clickable":
                        mental()
                        fsm = "clickable"
                    elif (not identical(last_clicked, widget)
                          and not (terminator(last_clicked, {"save", "yes", "done", "ok"}) and terminator(widget, {"save", "yes", "done", "ok"}))
                          and not (terminator(last_clicked, {"cancel", "no", "exit", "quit", "abort"}) and terminator(widget, {"cancel", "no", "exit", "quit", "abort"}))):
                        mental()
                elif widget.kind == "text":
                    # WidgetType.Text is selection-only. Source1651-1655
                    # resets the FSM without adding TextBox's mental step.
                    fsm = "initial"
                else:
                    if not identical(last_clicked, widget):
                        mental()
                    fsm = "initial"
            if demo.op == "point" and last_moved and last_moved.bounds == widget.bounds:
                warnings.append(path + ": redundant point suppressed (sameBounds); demonstration retained")
                continue
            home("mouse")
            if last_moved is None or last_moved.bounds != widget.bounds:
                emit("point", "demonstrated" if demo.op == "point" else "automatic",
                     rule("addMoveMouse:686-719;handleMoveMouse:1401-1427"),
                     target=widget.id, update={"mouse": list(widget.center)})
                last_moved = widget
            if demo.op == "point":
                fsm = "initial"
                continue
            transitions = [t for t in project.design.transitions if t.from_frame == frame.id and t.target == widget.id]
            transition = transitions[0] if transitions else None
            if transition and demo.transition != transition.id:
                fail(path + ".transition", f"click requires explicitly selected transition {transition.id!r}")
            if not transition and demo.transition is not None:
                fail(path + ".transition", f"transition {demo.transition!r} is not defined for this frame/widget")
            emit("click", "demonstrated", rule("handleMouseTap:1681-1688"), target=widget.id,
                 update={"focus": widget.id if widget.kind == "textbox" else None})
            last_clicked = widget
            if transition:
                if transition.delay_s:
                    emit("wait", "automatic", rule("handleTransitionDelay:1761-1778"), duration=transition.delay_s,
                         note="serial baseline barrier starts after click; no overlap")
                changed = transition.to_frame != frame.id
                emit("transition", "automatic", "cogtool_py:serial transition commit after response barrier", duration=0.0,
                     update={"frame": transition.to_frame, "focus": None if changed else state["focus"],
                             "look_target": None if changed else state["look_target"]}, note=transition.id)
        elif demo.op == "keys":
            global_keyboard = demo.device == "keyboard"
            if state["focus"] is None and not global_keyboard:
                fail(path + ".keys", "keyboard input requires initial focus or a prior textbox click")
            focus = frame.widget(state["focus"], path + ".keys.focus") if not global_keyboard else None
            if focus is not None and focus.kind != "textbox":
                fail(path + ".keys.focus", "keyboard focus is not a textbox")
            # Upstream scans the entire KeyAction for use of the mouse hand.
            # Homing occurs at sequence start, after an initial command Think.
            def uses_mouse_hand(key: str) -> bool:
                left = key in LEFT_KEYS or key == "ESC"
                return left == (initial.mouse_hand == "left")
            needs_home = any(uses_mouse_hand(k) for k in demo.keys)
            first = demo.keys[0]
            if demo.is_command:
                # KLM791-799: addMental is idempotent after a mental; this is
                # not a modifier or an application command interpreter.
                mental()
                fsm = "command_marker_no_char"
            if first in COMMAND_KEYS and (fsm != "command" or first != last_cmd):
                mental()
            if needs_home:
                home("keyboard")
            for i, key in enumerate(demo.keys):
                if key in COMMAND_KEYS:
                    if i != 0 and (fsm != "command" or key != last_cmd):
                        mental()
                    fsm, last_cmd = "command", key
                else:
                    fsm, last_cmd = "keystroke", None
                emit("key", "demonstrated", rule("handleKeyInput:815-883;TextActionSegment expanded into physical strokes"),
                     key=key, target=focus.id if focus is not None else None,
                     device="keyboard" if global_keyboard else None,
                     note=f"key_index={i}; US unshifted stroke; no application text simulation")
            if demo.transition is not None:
                transition = next(t for t in project.design.transitions if t.id == demo.transition)
                if transition.delay_s:
                    emit("wait", "automatic", rule("handleTransitionDelay:1761-1778"),duration=transition.delay_s,
                         note="device response annotation; integrated delay starts at last pending key output")
                changed = transition.to_frame != frame.id
                emit("transition", "automatic", rule("handleKeyInput/flushTextSegment:732-760;handleTransitionDelay:1761-1778"),duration=0.0,
                     update={"frame":transition.to_frame,"focus":None if changed else state["focus"],
                             "look_target":None if changed else state["look_target"]},note=transition.id)
        elif demo.op == "home":
            home(demo.device, "demonstrated")
            fsm = "initial"
        elif demo.op == "think":
            emit("think", "demonstrated", rule("addMentalStep:600-610"),
                 duration=demo.duration_s if demo.duration_s is not None else project.parameters.value("think_s"))
        elif demo.op == "look_at":
            if source_look:
                # KLM1923-1983 owns a distinct explicit-look history. Automatic
                # ACT-R writer looks do not update this KLM state.
                if last_explicit_look is not None and last_explicit_look.bounds == widget.bounds:
                    was_mental = last_mental
                    mental()
                    if was_mental:
                        warnings.append(path + ": source sameLocation LookAt already viewed; no new Look/Think")
                else:
                    was_mental = last_mental
                    emit("look_at", "demonstrated", rule("generateScriptSteps LookAt:1923-1983"),
                         target=demo.target, update={"look_target": demo.target},
                         note="source explicit attention request; no dwell duration or mouse action")
                    last_mental = was_mental  # duplicateState preserves mental flag.
                    last_explicit_look = widget
                    mental()
            else:
                emit("look_at", "demonstrated", "cogtool_py:explicit visual dwell; differs from generateScriptSteps:1923-1983/EMMA",
                     target=demo.target, duration=demo.duration_s, update={"look_target": demo.target},
                     note="explicit baseline block; suppresses immediately following automatic Think; no EMMA prediction")
                warnings.append(path + ": LookAt duration is modeler-supplied; upstream LookAt/Think coupling and EMMA are not implemented")
        elif demo.op == "wait":
            emit("wait", "demonstrated", "cogtool_py:explicit serial response barrier", duration=demo.duration_s)
            fsm = "initial"
        else:
            fail(path + ".op", f"unsupported operation {demo.op!r}; no partial script generated")
    return GeneratedScript(tuple(steps), tuple(warnings), dict(state))


def validate(project: Project) -> None:
    """Validate referential and demonstrated-state integrity for every task."""
    validate_project(project)
