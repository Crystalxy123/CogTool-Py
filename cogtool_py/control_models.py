"""Immutable, persisted inputs for the explicitly bounded 2014 control prefix.

Synthetic state updates test controller branches only, never EMMA timing.
All configuration participates in the existing Project content hash.
"""
from dataclasses import asdict, dataclass, fields, replace
import math

from .models import (choice, fail, finite_coordinate, number, obj, string)


@dataclass(frozen=True)
class AuxiliaryLocation:
    id: str
    frame: str
    x: float
    y: float
    source: str


@dataclass(frozen=True)
class SyntheticUpdate:
    at_s: float
    kind: str
    target: str | None = None
    requested: bool = False


UPDATE_KINDS = frozenset({"location_set", "location_clear", "visual_free", "visual_busy",
                         "scene_remove", "scene_add", "frame_hide", "frame_show",
                         "manual_busy", "manual_free"})


@dataclass(frozen=True)
class ControlConfig:
    profile: str
    provenance: str
    # Only the synthetic profile accepts prescribed buffers/module state.
    visual_location: str | None = None
    location_requested: bool = False
    visual_content: str | None = None
    visual_preparation: str = "free"
    visual_processor: str = "free"
    visual_execution: str = "free"
    frame_visible: bool = True
    auto_stuffing: bool = False
    visible_targets: tuple[str, ...] | None = None
    auxiliary_locations: tuple[AuxiliaryLocation, ...] = ()
    updates: tuple[SyntheticUpdate, ...] = ()
    max_events: int = 1000
    max_time_s: float = 10.0
    execution_scope: str = "prefix_only"
    initial_eye: tuple[float, float] | None = None
    run_policy: str = "legacy_bounded"

    @classmethod
    def source_2014(cls, *, provenance: str, auxiliary_locations=()):
        return cls("source_2014_defaults", provenance, auto_stuffing=True,
                   auxiliary_locations=tuple(auxiliary_locations))

    @classmethod
    def reference_2014(cls, *, provenance: str, auxiliary_locations=()):
        """Pinned default CogTool ACTR_TIMEOUT 600000 ms / 1000, not a fit."""
        return replace(cls.source_2014(provenance=provenance, auxiliary_locations=auxiliary_locations),
                       execution_scope="integrated_task", max_time_s=600.0, run_policy="reference_2014")

    @classmethod
    def parse(cls, value):
        names = {f.name for f in fields(cls)}
        d = dict(obj(value, "control", {"profile", "provenance"}, names - {"profile", "provenance"}))
        for key, target in (("auxiliary_locations", AuxiliaryLocation), ("updates", SyntheticUpdate)):
            if key in d:
                if not isinstance(d[key], list):
                    fail("control." + key, "expected an array")
                required = {f.name for f in fields(target) if f.name not in {"target", "requested"}}
                d[key] = tuple(target(**obj(item, f"control.{key}[{i}]", required,
                                            {f.name for f in fields(target)} - required))
                               for i, item in enumerate(d[key]))
        if d.get("visible_targets") is not None:
            if not isinstance(d["visible_targets"], list):
                fail("control.visible_targets", "expected an array or null")
            d["visible_targets"] = tuple(d["visible_targets"])
        if d.get("initial_eye") is not None:
            if not isinstance(d["initial_eye"], list):
                fail("control.initial_eye", "expected two coordinates or null")
            d["initial_eye"] = tuple(d["initial_eye"])
        result = cls(**d)
        validate_control(result)
        return result

    def to_dict(self):
        validate_control(self)
        result = asdict(self)
        if self.run_policy == "legacy_bounded":
            result.pop("run_policy")  # Preserve canonical legacy input hashes.
        result["visible_targets"] = list(self.visible_targets) if self.visible_targets is not None else None
        result["max_time_s"] = float(self.max_time_s)
        result["auxiliary_locations"] = [{**asdict(a), "x": float(a.x), "y": float(a.y)} for a in self.auxiliary_locations]
        result["updates"] = [{**asdict(e), "at_s": float(e.at_s)} for e in self.updates]
        # Preserve the canonical identity of previously saved prefix inputs.
        if self.execution_scope == "prefix_only":
            result.pop("execution_scope")
        if self.initial_eye is None:
            result.pop("initial_eye")
        else:
            result["initial_eye"] = [float(x) for x in self.initial_eye]
        return result


def validate_control(config):
    if type(config) is not ControlConfig:
        fail("control", "expected an explicit ControlConfig")
    for field in fields(ControlConfig):
        if not hasattr(config, field.name):
            fail("control." + field.name, "required field is missing")
    choice(config.run_policy, "control.run_policy", {"legacy_bounded", "reference_2014"})
    if config.run_policy == "reference_2014" and (config.max_time_s != 600.0 or config.profile != "source_2014_defaults" or config.execution_scope != "integrated_task"):
        fail("control.run_policy", "reference_2014 fixes source-default integrated simulation limit at 600 seconds; use legacy_bounded for custom limits")
    choice(config.profile, "control.profile", {"source_2014_defaults", "synthetic_controller_only"})
    choice(config.execution_scope, "control.execution_scope", {"prefix_only", "integrated_task"})
    if config.initial_eye is not None:
        if type(config.initial_eye) is not tuple or len(config.initial_eye) != 2:
            fail("control.initial_eye", "expected immutable pair of coordinates")
        for i, value in enumerate(config.initial_eye):
            finite_coordinate(value, f"control.initial_eye[{i}]")
        if config.profile == "source_2014_defaults" or config.execution_scope != "integrated_task":
            fail("control.initial_eye", "prescribed fixation only belongs to synthetic integrated input")
    if config.execution_scope == "integrated_task":
        if config.visual_content is not None or config.updates or any(getattr(config, field) != "free" for field in
                                ("visual_preparation", "visual_processor", "visual_execution")):
            fail("control", "integrated vision requires actual module events; no prescribed visual content/busy state or synthetic completion updates")
    string(config.provenance, "control.provenance")
    for name in ("visual_location", "visual_content"):
        if getattr(config, name) is not None:
            string(getattr(config, name), "control." + name)
    for name in ("location_requested", "frame_visible", "auto_stuffing"):
        if type(getattr(config, name)) is not bool:
            fail("control." + name, "expected a boolean")
    for name in ("visual_preparation", "visual_processor", "visual_execution"):
        choice(getattr(config, name), "control." + name, {"free", "busy"})
    if config.visible_targets is not None:
        if type(config.visible_targets) is not tuple:
            fail("control.visible_targets", "expected an immutable tuple or null")
        for i, target in enumerate(config.visible_targets):
            string(target, f"control.visible_targets[{i}]")
        if len(set(config.visible_targets)) != len(config.visible_targets):
            fail("control.visible_targets", "duplicate target")
    if type(config.auxiliary_locations) is not tuple or type(config.updates) is not tuple:
        fail("control", "locations and updates must be immutable tuples")
    ids = []
    for i, a in enumerate(config.auxiliary_locations):
        path = f"control.auxiliary_locations[{i}]"
        if type(a) is not AuxiliaryLocation:
            fail(path, "expected AuxiliaryLocation")
        for field in fields(AuxiliaryLocation):
            if not hasattr(a, field.name):
                fail(path + "." + field.name, "required field is missing")
        for name in ("id", "frame", "source"):
            string(getattr(a, name), path + "." + name)
        finite_coordinate(a.x, path + ".x")
        finite_coordinate(a.y, path + ".y")
        ids.append((a.frame, a.id))
    if len(ids) != len(set(ids)):
        fail("control.auxiliary_locations", "duplicate frame/location id")
    for i, event in enumerate(config.updates):
        path = f"control.updates[{i}]"
        if type(event) is not SyntheticUpdate:
            fail(path, "expected SyntheticUpdate")
        for field in fields(SyntheticUpdate):
            if not hasattr(event, field.name):
                fail(path + "." + field.name, "required field is missing")
        number(event.at_s, path + ".at_s")
        if not math.isfinite(event.at_s / .001):
            fail(path + ".at_s", "time is outside the finite millisecond range")
        choice(event.kind, path + ".kind", UPDATE_KINDS)
        if type(event.requested) is not bool:
            fail(path + ".requested", "expected a boolean")
        if event.kind in {"location_set", "scene_add", "scene_remove"}:
            string(event.target, path + ".target")
        elif event.target is not None and event.kind != "visual_free":
            fail(path + ".target", "target is not used by this update kind")
        elif event.target is not None:
            string(event.target, path + ".target")
        if event.requested and event.kind != "location_set":
            fail(path + ".requested", "only location_set uses requested provenance")
    if type(config.max_events) is not int or not 1 <= config.max_events <= 100000:
        fail("control.max_events", "expected integer in [1, 100000]")
    number(config.max_time_s, "control.max_time_s", positive=True)
    if not math.isfinite(config.max_time_s / .001):
        fail("control.max_time_s", "time is outside the finite millisecond range")
    if config.profile == "source_2014_defaults":
        if (config.visual_location is not None or config.location_requested or config.visual_content is not None
                or any(getattr(config, field) != "free" for field in
                       ("visual_preparation", "visual_processor", "visual_execution"))
                or not config.frame_visible or not config.auto_stuffing
                or config.visible_targets is not None or config.updates):
            fail("control", "source_2014_defaults cannot contain prescribed/synthetic state; use synthetic_controller_only")


def validate_control_references(project):
    """Called after the shared project design/task validation."""
    config = project.control
    known = {(frame.id, w.id) for frame in project.design.frames for w in frame.widgets}
    for a in config.auxiliary_locations:
        project.design.frame(a.frame, "control.auxiliary_locations")
        if (a.frame, a.id) in known:
            fail("control.auxiliary_locations", f"id {a.id!r} collides with a design widget")
        known.add((a.frame, a.id))
    for task in project.tasks:
        frame = task.demonstration.initial.frame
        if config.profile == "source_2014_defaults" and tuple(task.demonstration.initial.mouse) != (0, 0):
            fail(f"task[{task.id}].initial.mouse", "source_2014_defaults resets cursor to (0,0); use a synthetic profile for prescribed coordinates")
        targets = (config.visual_location, config.visual_content, *(config.visible_targets or ()),
                   *(e.target for e in config.updates))
        for target in targets:
            if target is not None and (frame, target) not in known:
                fail(f"task[{task.id}].control.target", f"unknown initial-frame location {target!r}")
