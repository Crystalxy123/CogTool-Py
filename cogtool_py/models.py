"""Strict, inert JSON data model. Parsing never executes model content.

Structural concepts follow CogTool; this schema is deliberately not its file format.
See NOTICE.md for provenance and docs/model_semantics.md for baseline differences.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
import math
from types import MappingProxyType
from typing import Any

from . import JAVA_MODEL, source


class ModelError(ValueError):
    """A model field or a demonstrated state transition is invalid."""


def fail(path: str, message: str) -> None:
    raise ModelError(f"{path}: {message}")


def obj(value: Any, path: str, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        fail(path, "expected an object")
    if any(type(key) is not str for key in value):
        fail(path, "object field names must be strings")
    if set(value) - required - optional:
        fail(path, f"unsupported field(s): {sorted(set(value) - required - optional)}")
    if required - set(value):
        fail(path, f"missing field(s): {sorted(required - set(value))}")
    return value


def string(value: Any, path: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        fail(path, "expected a nonempty string" if not empty else "expected a string")
    return value


def number(value: Any, path: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(path, "expected a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        fail(path, "number is out of range")
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        fail(path, "expected a finite positive number" if positive else "expected a finite nonnegative number")
    return 0.0 if result == 0 else result


def finite_coordinate(value: Any, path: str) -> float:
    """Coordinates may be negative; durations and dimensions still use number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(path, "expected a finite coordinate")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        fail(path, "coordinate is out of range")
    if not math.isfinite(result):
        fail(path, "expected a finite coordinate")
    return 0.0 if result == 0 else result


def choice(value: Any, path: str, options: set[str]) -> str:
    if not isinstance(value, str) or value not in options:
        fail(path, f"unsupported value {value!r}; supported: {sorted(options)}")
    return value


def array(value: Any, path: str, *, nonempty: bool = True) -> list:
    if not isinstance(value, list) or (nonempty and not value):
        fail(path, "expected a nonempty array" if nonempty else "expected an array")
    return value


def unique(items: tuple, path: str) -> None:
    seen = set()
    for item in items:
        if item.id in seen:
            fail(path, f"duplicate id {item.id!r}")
        seen.add(item.id)


@dataclass(frozen=True)
class Parameter:
    value: float
    unit: str
    source: str
    kind: str
    scope: str
    overridable: bool = True
    default_version: str = "cogtool-py-defaults-v1"


DEFAULTS = MappingProxyType({
    "think_s": Parameter(1.2, "s", source(JAVA_MODEL + "ThinkScriptStep.java", "DEFAULT_KLM_THINK_DURATION:117"), "upstream_default", "explicit and generated Think; full block"),
    "fitts_coefficient_s": Parameter(0.1, "s", source("lisp/actr6/framework/device-interface.lisp", "mouse-fitts-coeff:232"), "upstream_component", "cursor movement component only"),
    "fitts_min_s": Parameter(0.1, "s", source("java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp", ":min-fitts-time:554-558"), "upstream_component", "minimum aimed movement component"),
    "motor_initiation_s": Parameter(0.05, "s", source("java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp", ":motor-initiation-time:564-568"), "upstream_component", "point initiation; not added to click/key/homing blocks"),
    "pixels_per_inch": Parameter(72.0, "px/in", source("lisp/actr6/framework/device-interface.lisp", "pixels-per-inch:154-155,222-224"), "upstream_default", "model coordinates, not monitor auto-detection"),
    "viewing_distance_in": Parameter(15.0, "in", source("lisp/actr6/framework/device-interface.lisp", "viewing-distance:225"), "upstream_default", "pixel-to-angle conversion"),
})
REQUIRED_TIMES = frozenset({"click_s", "key_s", "homing_s"})
CORE_PARAMETER_NAMES = frozenset(DEFAULTS) | REQUIRED_TIMES
MOTOR_ENGINE = "cogtool_motor_subset_experimental"
CONTROL_ENGINE = "cogtool_control_prefix_experimental"
ENGINE_NAMES = frozenset({"klm_baseline", MOTOR_ENGINE, CONTROL_ENGINE})
# Opt-in profile: do not change the effective values or hashes of baseline files.
MOTOR_DEFAULTS = MappingProxyType({
    "motor_feature_prep_s": Parameter(.001, "s", source("java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp", ":motor-feature-prep-time:569-574"), "upstream_component", "per changed movement feature", default_version="cogtool-a91d91e-motor-v1"),
    "motor_burst_s": Parameter(.05, "s", source("java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp", ":motor-burst-time:560-564"), "upstream_component", "motor execution release", default_version="cogtool-a91d91e-motor-v1"),
    "motor_key_closure_s": Parameter(.01, "s", source("lisp/actr6/framework/device-interface.lisp", "key-closure-time:227"), "upstream_component", "punch output after initiation", default_version="cogtool-a91d91e-motor-v1"),
})
KEYBOARD_DEFAULTS = MappingProxyType({
    "motor_peck_fitts_coefficient_s": Parameter(.075, "s", source("java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp", ":peck-fitts-coeff:575-579"), "upstream_component", "unshifted virtual-keyboard peck-recoil movement; no serial key_s/homing_s block", default_version="cogtool-a91d91e-keyboard-v1"),
})
CONTROL_DEFAULTS = MappingProxyType({
    "production_action_s": Parameter(.05, "s", source("lisp/actr6/core-modules/procedural.lisp", ":dat:1968-1969;production-selected:1875-1887") + "; " + source("java/edu/cmu/cs/hcii/cogtool/model/ACTRPredictionAlgo.java", "generated DAT from CogToolPref.ACTR_DAT:464-473") + "; " + source("java/edu/cmu/cs/hcii/cogtool/CogToolPref.java", "ACTR_DAT default 50 ms:132"), "upstream_component", "default production :at cached from :dat; explicit SET-START-FRAME :at=0 overrides", default_version="cogtool-a91d91e-control-v1"),
})
_EMMA = "java/edu/cmu/cs/hcii/cogtool/resources/emma.lisp"
VISION_DEFAULTS = MappingProxyType({
    "visual_encoding_factor_s": Parameter(.006, "s", source("java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp", "default-global-parameters:1118-1125"), "upstream_component", "EMMA encoding factor", default_version="cogtool-a91d91e-vision-v1"),
    "visual_encoding_exponent_per_deg": Parameter(.4, "1/deg", source("java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp", "default-global-parameters:1118-1125"), "upstream_component", "EMMA eccentricity exponent", default_version="cogtool-a91d91e-vision-v1"),
    "visual_object_frequency": Parameter(.01, "probability", source(_EMMA, "object-frequency:525-536;vis-obj-freq:895-899"), "upstream_default", "string-valued object without registered frequency; restricted to 0 < f <= 1", default_version="cogtool-a91d91e-vision-v1"),
    "eye_feature_prep_s": Parameter(.05, "s", source("lisp/actr6/support/general-pm.lisp", "pm-module:222-225;compute-prep-time:650-655"), "upstream_component", "vision feature preparation; motor override does not change vision", default_version="cogtool-a91d91e-vision-v1"),
    "eye_initiation_s": Parameter(.05, "s", source("lisp/actr6/support/general-pm.lisp", "pm-module:224-225"), "upstream_component", "EMMA saccade initiation component", default_version="cogtool-a91d91e-vision-v1"),
    "eye_saccade_rate_s_per_deg": Parameter(.002, "s/deg", source(_EMMA, "compute-exec-time:203-206;EYE-SACCADE-RATE:885-889"), "upstream_component", "EMMA angular saccade execution rate", default_version="cogtool-a91d91e-vision-v1"),
    "eye_saccade_base_s": Parameter(.02, "s", source(_EMMA, "compute-exec-time:203-206;SACCADE-BASE-TIME:890-894"), "upstream_component", "EMMA saccade execution intercept", default_version="cogtool-a91d91e-vision-v1"),
})
ALL_DEFAULTS = MappingProxyType({**DEFAULTS, **MOTOR_DEFAULTS, **KEYBOARD_DEFAULTS, **CONTROL_DEFAULTS, **VISION_DEFAULTS})
PARAMETER_NAMES = frozenset(ALL_DEFAULTS) | REQUIRED_TIMES
PARAMETER_FIELDS = frozenset({"value", "unit", "source", "kind", "scope", "overridable", "default_version"})
SUPPLIED_SCOPE = "serial baseline whole-operation duration; not an ACT-R default"


@dataclass(frozen=True)
class ParameterSet:
    entries: Mapping[str, Parameter]

    def __post_init__(self) -> None:
        self.validate()
        # Copy the caller's mapping, and normalize validated scalar values. The
        # frozen Parameter objects contain no mutable children after validation.
        object.__setattr__(self, "entries", MappingProxyType({
            name: replace(p, value=number(p.value, f"parameters.{name}.value",
                                         positive=name in {"pixels_per_inch", "viewing_distance_in"}))
            for name, p in self.entries.items()
        }))

    def validate(self, path: str = "parameters") -> None:
        if not isinstance(self.entries, Mapping):
            fail(path, "expected a parameter mapping")
        if any(type(name) is not str for name in self.entries):
            fail(path, "parameter names must be strings")
        names = set(self.entries)
        if names - PARAMETER_NAMES:
            fail(path, f"unsupported field(s): {sorted(names - PARAMETER_NAMES)}")
        if CORE_PARAMETER_NAMES - names:
            fail(path, f"missing effective parameter(s): {sorted(CORE_PARAMETER_NAMES - names)}")
        if names & MOTOR_DEFAULTS.keys() and not MOTOR_DEFAULTS.keys() <= names:
            fail(path, "motor subset profile must contain all three motor parameters")
        if names & KEYBOARD_DEFAULTS.keys() and not MOTOR_DEFAULTS.keys() <= names:
            fail(path, "keyboard profile requires all effective motor parameters")
        if names & VISION_DEFAULTS.keys() and not VISION_DEFAULTS.keys() <= names:
            fail(path, "integrated vision profile must contain all effective vision parameters")
        for name, p in self.entries.items():
            field = f"{path}.{name}"
            if type(p) is not Parameter:
                fail(field, "expected a Parameter")
            number(p.value, field + ".value", positive=name in {"pixels_per_inch", "viewing_distance_in"})
            if name == "visual_object_frequency" and not 0 < p.value <= 1:
                fail(field + ".value", "integrated string frequency requires 0 < value <= 1")
            unit = ALL_DEFAULTS[name].unit if name in ALL_DEFAULTS else "s"
            if p.unit != unit or type(p.unit) is not str:
                fail(field + ".unit", f"expected {unit!r}; unit conversion is not supported")
            string(p.source, field + ".source")
            choice(p.kind, field + ".kind", {"upstream_default", "upstream_component", "modeler_supplied"})
            string(p.scope, field + ".scope")
            if type(p.overridable) is not bool:
                fail(field + ".overridable", "expected a boolean")
            string(p.default_version, field + ".default_version")

    @classmethod
    def parse(cls, value: Any, schema_version: int = 1) -> ParameterSet:
        if type(schema_version) is not int or schema_version not in {1, 2}:
            fail("schema_version", "only integer versions 1 and 2 are supported")
        d = obj(value, "parameters", CORE_PARAMETER_NAMES if schema_version == 2 else REQUIRED_TIMES,
                set(MOTOR_DEFAULTS) | set(KEYBOARD_DEFAULTS) | set(CONTROL_DEFAULTS) | set(VISION_DEFAULTS) if schema_version == 2 else set(ALL_DEFAULTS))
        entries = {} if schema_version == 2 else dict(DEFAULTS)
        for name, entry in d.items():
            p = f"parameters.{name}"
            # v1 callers may already hold input_dict() with full metadata. Accept
            # that complete shape without discarding its provenance.
            full = schema_version == 2 or (isinstance(entry, dict) and bool(set(entry) & (PARAMETER_FIELDS - {"value", "unit", "source"})))
            e = obj(entry, p, PARAMETER_FIELDS if full else {"value", "unit", "source"})
            if full:
                entries[name] = Parameter(**e)
            else:
                entries[name] = Parameter(
                    e["value"], e["unit"], e["source"], "modeler_supplied",
                    ALL_DEFAULTS[name].scope if name in ALL_DEFAULTS else SUPPLIED_SCOPE,
                    default_version=ALL_DEFAULTS[name].default_version if name in ALL_DEFAULTS else "modeler-supplied-v1",
                )
        return cls(entries)

    def with_motor_defaults(self) -> ParameterSet:
        """Explicitly opt into the pinned upstream motor profile, without mutation.

        Existing overrides win. Schema 2 files must store the complete profile;
        switching only an engine name never silently supplies missing parameters.
        """
        self.validate()
        entries = {**MOTOR_DEFAULTS, **self.entries}
        if not MOTOR_DEFAULTS.keys() <= self.entries.keys():
            entries["motor_initiation_s"] = replace(entries["motor_initiation_s"],
                scope="motor subset: initiation of cursor and punch; klm_baseline: point initiation only")
        return type(self)(entries)

    def with_control_defaults(self) -> ParameterSet:
        """Opt into the pinned prefix parameters; use the same immutable lifecycle."""
        motor = self.with_motor_defaults()
        return type(self)({**CONTROL_DEFAULTS, **motor.entries})

    def with_keyboard_defaults(self) -> ParameterSet:
        """Opt into virtual-keyboard mechanics without changing old profiles."""
        motor = self.with_motor_defaults()
        return type(self)({**KEYBOARD_DEFAULTS, **motor.entries})

    def with_vision_defaults(self) -> ParameterSet:
        """Explicit integrated scope; never add visual parameters to old inputs."""
        control = self.with_control_defaults()
        return type(self)({**VISION_DEFAULTS, **control.entries})

    def override(self, name: str, value: Any, *, source: str, unit: str | None = None) -> ParameterSet:
        """Return a separately validated set; changing a value needs provenance."""
        self.validate()
        if type(name) is not str or name not in self.entries:
            fail("parameters", f"unknown override parameter {name!r}")
        current = self.entries[name]
        if not current.overridable:
            fail(f"parameters.{name}", "parameter is not overridable")
        entries = dict(self.entries)
        entries[name] = replace(current, value=value, source=source,
                                unit=current.unit if unit is None else unit, kind="modeler_supplied")
        return type(self)(entries)

    def value(self, name: str) -> float:
        return self.entries[name].value

    def input_dict(self) -> dict:
        """All effective values and provenance, suitable for schema 2 persistence."""
        self.validate()
        return {name: asdict(p) for name, p in self.entries.items()}

    def result_dict(self) -> dict:
        return self.input_dict()


@dataclass(frozen=True)
class Widget:
    id: str
    name: str
    label: str
    kind: str
    x: float
    y: float
    width: float
    height: float
    parent: str | None = None

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.x, self.y, self.width, self.height

    @property
    def center(self) -> tuple[float, float]:
        # cogtool-actr.lisp frame-vis-loc-template floors each half-dimension.
        return self.x + math.floor(self.width / 2), self.y + math.floor(self.height / 2)

    @classmethod
    def parse(cls, value: Any, path: str) -> Widget:
        d = obj(value, path, {"id", "name", "label", "kind", "x", "y", "width", "height"}, {"parent"})
        return cls(string(d["id"], path + ".id"), string(d["name"], path + ".name"),
                   string(d["label"], path + ".label", empty=True),
                   choice(d["kind"], path + ".kind", {"button", "link", "textbox", "text", "context_menu", "menu_item"}),
                   *(finite_coordinate(d[k], path + "." + k) for k in ("x", "y")),
                   *(number(d[k], path + "." + k, positive=True) for k in ("width", "height")),
                   string(d["parent"], path + ".parent") if d.get("parent") is not None else None)


@dataclass(frozen=True)
class InputDevice:
    """A frame-owned source of input transitions, never a geometric widget."""
    id: str
    name: str
    kind: str = "keyboard"

    @classmethod
    def parse(cls, value, path):
        d = obj(value, path, {"id", "name", "kind"})
        return cls(string(d["id"], path + ".id"), string(d["name"], path + ".name"),
                   choice(d["kind"], path + ".kind", {"keyboard"}))


@dataclass(frozen=True)
class Frame:
    id: str
    name: str
    widgets: tuple[Widget, ...]
    devices: tuple[InputDevice, ...] = ()

    def widget(self, ident: str | None, path: str) -> Widget:
        for w in self.widgets:
            if w.id == ident:
                return w
        fail(path, f"widget {ident!r} does not exist in frame {self.id!r}")

    def device(self, ident: str, path: str) -> InputDevice:
        for device in self.devices:
            if device.id == ident:
                return device
        fail(path, f"input device {ident!r} does not belong to frame {self.id!r}")


@dataclass(frozen=True)
class Transition:
    id: str
    from_frame: str
    target: str | None
    to_frame: str
    delay_s: float
    delay_label: str | None = None
    source_type: str = "widget"
    source_id: str | None = None
    keys: tuple[str, ...] = ()
    is_command: bool = False
    modifiers: int = 0
    key_text: str | None = None

    def to_dict(self):
        d = {"id":self.id, "from_frame":self.from_frame, "to_frame":self.to_frame,
             "delay_s":number(self.delay_s, "transition.delay_s")}
        if self.delay_label is not None:
            d["delay_label"] = self.delay_label
        if self.source_type == "widget":
            d["target"] = self.target
        else:
            d.update(source_type=self.source_type, source_id=self.source_id,
                     keys=list(self.keys), is_command=self.is_command, modifiers=self.modifiers)
            if self.key_text is not None:d["key_text"] = self.key_text
        return d


@dataclass(frozen=True)
class Design:
    id: str
    name: str
    coordinate_unit: str
    frames: tuple[Frame, ...]
    transitions: tuple[Transition, ...]

    def frame(self, ident: str, path: str) -> Frame:
        for frame in self.frames:
            if frame.id == ident:
                return frame
        fail(path, f"frame {ident!r} does not exist")


# Physical, unshifted US-keyboard strokes, not arbitrary Unicode text.
LEFT_KEYS = set("qwertasdfgzxcvb12345` ")
RIGHT_KEYS = set("yuiophjklnm67890-=[]\\;',./")
COMMAND_KEYS = {"ENTER", "BACKSPACE", "DELETE", "ESC", "UP", "DOWN", "LEFT", "RIGHT"}
SUPPORTED_KEYS = LEFT_KEYS | RIGHT_KEYS | COMMAND_KEYS


@dataclass(frozen=True)
class DemonstrationStep:
    op: str
    target: str | None = None
    keys: tuple[str, ...] = ()
    duration_s: float | None = None
    device: str | None = None
    transition: str | None = None
    is_command: bool = False
    modifiers: int = 0
    device_id: str | None = None
    key_text: str | None = None

    @classmethod
    def parse(cls, value: Any, path: str) -> DemonstrationStep:
        if not isinstance(value, dict):
            fail(path, "expected an operation object")
        op = choice(value.get("op"), path + ".op", {"point", "click", "menu_select", "keys", "home", "think", "look_at", "wait"})
        required = {"op"}
        optional: set[str] = set()
        if op in {"point", "click", "menu_select", "look_at"}:
            required.add("target")
        if op in {"click", "menu_select"}:
            optional.add("transition")
        if op == "keys":
            required.add("keys")
            optional.update({"device", "device_id", "transition", "is_command", "modifiers", "key_text"})
        if op == "wait":
            required.add("duration_s")
        if op == "look_at":
            optional.add("duration_s")
        if op == "think":
            optional.add("duration_s")
        if op == "home":
            required.add("device")
        d = obj(value, path, required, optional)
        keys = []
        if op == "keys":
            for i, key in enumerate(array(d["keys"], path + ".keys")):
                keys.append(choice(key, f"{path}.keys[{i}] (IME/shift/chords unsupported)", SUPPORTED_KEYS))
        return cls(op,
                   string(d["target"], path + ".target") if "target" in d else None,
                   tuple(keys),
                   number(d["duration_s"], path + ".duration_s") if "duration_s" in d else None,
                   choice(d["device"], path + ".device", {"keyboard"} if op == "keys" else {"mouse", "keyboard"}) if "device" in d else None,
                   string(d["transition"], path + ".transition") if "transition" in d else None,
                   d.get("is_command", False), d.get("modifiers", 0),
                   string(d["device_id"], path + ".device_id") if "device_id" in d else None,
                   string(d["key_text"], path + ".key_text") if "key_text" in d else None)

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"op": self.op}
        for key in ("target", "duration_s", "device", "transition", "device_id", "key_text"):
            value = getattr(self, key)
            if value is not None:
                d[key] = number(value, "step.duration_s") if key == "duration_s" else value
        if self.keys:
            d["keys"] = list(self.keys)
        # Defaults retain the normalized identity of existing schema 1/2 files.
        if self.is_command:
            d["is_command"] = self.is_command
        if self.modifiers:
            d["modifiers"] = self.modifiers
        return d


@dataclass(frozen=True)
class InitialState:
    frame: str
    mouse: tuple[float, float]
    mouse_hand: str
    hand: str
    focus: str | None


@dataclass(frozen=True)
class Demonstration:
    initial: InitialState
    steps: tuple[DemonstrationStep, ...]


@dataclass(frozen=True)
class Task:
    id: str
    name: str
    demonstration: Demonstration


@dataclass(frozen=True)
class Project:
    schema_version: int
    id: str
    name: str
    engine: str
    parameters: ParameterSet
    design: Design
    tasks: tuple[Task, ...]
    control: Any = None

    @classmethod
    def from_dict(cls, value: Any) -> Project:
        d = obj(value, "project", {"schema_version", "id", "name", "engine", "parameters", "design", "tasks"}, {"control"})
        if type(d["schema_version"]) is not int or d["schema_version"] not in {1, 2}:
            fail("schema_version", "only integer versions 1 and 2 are supported")
        engine = choice(d["engine"], "engine (no automatic fallback)", ENGINE_NAMES)
        design_data = obj(d["design"], "design", {"id", "name", "coordinate_unit", "frames", "transitions"})
        choice(design_data["coordinate_unit"], "design.coordinate_unit", {"px"})
        frames = []
        for i, fd in enumerate(array(design_data["frames"], "design.frames")):
            p = f"design.frames[{i}]"
            fd = obj(fd, p, {"id", "name", "widgets"}, {"devices"})
            widgets = tuple(Widget.parse(w, f"{p}.widgets[{j}]") for j, w in enumerate(array(fd["widgets"], p + ".widgets", nonempty=False)))
            unique(widgets, p + ".widgets")
            devices = tuple(InputDevice.parse(v, f"{p}.devices[{j}]") for j,v in
                            enumerate(array(fd.get("devices", []), p + ".devices", nonempty=False)))
            frames.append(Frame(string(fd["id"], p + ".id"), string(fd["name"], p + ".name"), widgets, devices))
        unique(tuple(frames), "design.frames")
        transitions = []
        for i, tr in enumerate(array(design_data["transitions"], "design.transitions", nonempty=False)):
            p = f"design.transitions[{i}]"
            tr = obj(tr, p, {"id", "from_frame", "to_frame", "delay_s"},
                     {"target", "delay_label", "source_type", "source_id", "keys", "is_command", "modifiers", "key_text"})
            transitions.append(Transition(string(tr["id"],p+".id"), string(tr["from_frame"],p+".from_frame"),
                string(tr["target"],p+".target") if "target" in tr else None, string(tr["to_frame"],p+".to_frame"),
                number(tr["delay_s"],p+".delay_s"), string(tr["delay_label"],p+".delay_label",empty=True) if "delay_label" in tr else None,
                tr.get("source_type","widget"),tr.get("source_id"),
                tuple(array(tr.get("keys",[]),p+".keys",nonempty=False)),tr.get("is_command",False),tr.get("modifiers",0),tr.get("key_text")))
        unique(tuple(transitions), "design.transitions")
        design = Design(string(design_data["id"], "design.id"), string(design_data["name"], "design.name"), "px", tuple(frames), tuple(transitions))
        # Referential validation is shared with the actual-object API below.
        tasks = []
        for i, td in enumerate(array(d["tasks"], "tasks")):
            p = f"tasks[{i}]"
            td = obj(td, p, {"id", "name", "demonstration"})
            task_id = string(td["id"], p + ".id")
            p = f"task[{task_id}]"
            demo = obj(td["demonstration"], p + ".demonstration", {"initial", "steps"})
            initial = obj(demo["initial"], p + ".initial", {"frame", "mouse", "mouse_hand", "hand", "focus"})
            mouse = array(initial["mouse"], p + ".initial.mouse")
            if len(mouse) != 2:
                fail(p + ".initial.mouse", "expected [x, y] in px")
            frame = string(initial["frame"], p + ".initial.frame")
            f = design.frame(frame, p + ".initial.frame")
            focus = initial["focus"]
            if focus is not None:
                string(focus, p + ".initial.focus")
                if f.widget(focus, p + ".initial.focus").kind != "textbox":
                    fail(p + ".initial.focus", "focus must be a textbox")
            state = InitialState(frame, tuple(finite_coordinate(v, f"{p}.initial.mouse[{i}]") for i, v in enumerate(mouse)),
                                 choice(initial["mouse_hand"], p + ".initial.mouse_hand", {"right", "left"}),
                                 choice(initial["hand"], p + ".initial.hand", {"mouse", "keyboard"}), focus)
            steps = tuple(DemonstrationStep.parse(s, f"{p}.steps[{j}]") for j, s in enumerate(array(demo["steps"], p + ".steps")))
            tasks.append(Task(task_id, string(td["name"], p + ".name"), Demonstration(state, steps)))
        unique(tuple(tasks), "tasks")
        from .control_models import ControlConfig
        control = ControlConfig.parse(d["control"]) if d.get("control") is not None else None
        project = cls(2, string(d["id"], "project.id"), string(d["name"], "project.name"), engine,
                      ParameterSet.parse(d["parameters"], d["schema_version"]), design, tuple(tasks), control)
        from .validation import validate_project
        validate_project(project)
        return project

    def to_dict(self) -> dict:
        from .validation import validate_project
        validate_project(self)
        return {
            "schema_version": 2, "id": self.id, "name": self.name, "engine": self.engine,
            **({"control": self.control.to_dict()} if self.control is not None else {}),
            "parameters": self.parameters.input_dict(), "design": {
                "id": self.design.id, "name": self.design.name, "coordinate_unit": "px",
                "frames": [{"id": f.id, "name": f.name, "widgets": [
                    {**asdict(w),
                     **{key: finite_coordinate(getattr(w, key), "widget." + key) for key in ("x", "y")},
                     **{key: number(getattr(w, key), "widget." + key, positive=True) for key in ("width", "height")}}
                    for w in f.widgets], **({"devices":[asdict(v) for v in f.devices]} if f.devices else {})} for f in self.design.frames],
                "transitions": [t.to_dict() for t in self.design.transitions],
            },
            "tasks": [{"id": t.id, "name": t.name, "demonstration": {
                "initial": {**asdict(t.demonstration.initial), "mouse": [
                    finite_coordinate(v, "initial.mouse") for v in t.demonstration.initial.mouse]},
                "steps": [s.to_dict() for s in t.demonstration.steps]}} for t in self.tasks],
        }
