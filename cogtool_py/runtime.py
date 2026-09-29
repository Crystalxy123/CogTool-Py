"""Installed public entry helpers; never load research scripts or reference tools.

These helpers describe or assert an existing configuration. They do not change
parameters, select a different calculation policy, or fall back to another engine.
"""
from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path

from . import ENGINE_VERSION, UPSTREAM, __version__
from .models import ALL_DEFAULTS, CONTROL_ENGINE, MOTOR_ENGINE, ModelError, Project


def require_configuration(project: Project, *, engine: str | None = None,
                          scope: str | None = None, run_policy: str | None = None) -> Project:
    """Validate and assert saved choices, without silently converting a model."""
    from .validation import validate_project
    validate_project(project)
    actual_scope = project.control.execution_scope if project.control is not None else None
    actual_policy = project.control.run_policy if project.control is not None else None
    for name, expected, actual in (("engine", engine, project.engine),
                                   ("scope", scope, actual_scope),
                                   ("run_policy", run_policy, actual_policy)):
        if expected is not None and expected != actual:
            raise ModelError(f"configuration.{name}: requested {expected!r}, saved input is {actual!r}; no automatic conversion or fallback")
    return project


def run_project(path: str | Path, *, engine: str | None = None, scope: str | None = None,
                run_policy: str | None = None, task_id: str | None = None):
    """Load, independently validate the requested mode, then actually predict."""
    from .engine import predict
    from .io import load_project
    project = require_configuration(load_project(path), engine=engine, scope=scope, run_policy=run_policy)
    return predict(project, task_id)


def execution_identity(data: dict) -> dict:
    """Additive result metadata only; no change to any computed event or state."""
    engine = data["engine"]["name"]
    config = data.get("control_configuration") or {}
    status = data.get("completion_status", "complete" if data["predicted_time_s"] is not None else "partial")
    scope = config.get("execution_scope", "prefix_only") if engine == CONTROL_ENGINE else (
        "serial_baseline" if engine == "klm_baseline" else "motor_subset")
    policy = config.get("run_policy", "legacy_bounded") if config else None
    parameters = data["parameters"]
    digest = hashlib.sha256(json.dumps(parameters, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {
        "metadata_schema_version": 1, "package_version": __version__,
        "engine": engine, "engine_version": data["engine"]["version"],
        "scope": scope, "run_policy": policy,
        "run_policy_version": 1 if policy == "reference_2014" else None,
        "input_schema_supported": [1, 2], "canonical_saved_input_schema": 2,
        "parameter_sha256": digest,
        "default_parameter_versions": sorted({p["default_version"] for p in parameters.values()}),
        "input_sha256": data["input_sha256"], "execution_status": status,
        "termination_reason": data.get("termination_reason", "serial_operators_exhausted" if engine == "klm_baseline" else
                                       "bounded_scope_completed" if status == "complete" else "bounded_scope_incomplete"),
        "program_runtime_field": "program_runtime_s", "prediction_field": "predicted_time_s",
    }


def software_info() -> dict:
    from .control_prefix import VERSION as PREFIX_VERSION
    from .motor_subset import VERSION as MOTOR_VERSION
    return {
        "package": "cogtool-py", "package_version": __version__, "release_status": "local_release_candidate",
        "default_example_engine": "klm_baseline", "selection": "saved engine required; CLI assertions never override input",
        "engines": {"klm_baseline": {"version": ENGINE_VERSION, "scope": "serial_baseline"},
            MOTOR_ENGINE: {"version": MOTOR_VERSION, "scope": "motor_subset"},
            CONTROL_ENGINE: {"prefix_only_version": PREFIX_VERSION, "integrated_task_version": "0.6.0"}},
        "input_schema": {"read": [1, 2], "write": 2}, "result_schema_version": 1,
        "default_parameter_versions": sorted({v.default_version for v in ALL_DEFAULTS.values()}),
        "run_policies": {"legacy_bounded": {"default_simulation_limit_s": 10, "retained": True},
            "reference_2014": {"version": 1, "simulation_limit_s": 600, "event_limit": 1000,
                               "event_limit_scope": "Python only", "scope": "integrated_task"}},
        "upstream": UPSTREAM, "third_party_runtime_dependencies": [],
        "reference_tools_required_for_prediction": False, "supported_python_specifier": ">=3.11",
        "tested_environment": {"os": "macOS 15.6 arm64", "python": "3.11.15"},
        "other_platforms_or_python_versions_tested": False,
        "integrated_supported": ["known-target visual/motor/production subset", "ordinary Text click", "explicit LookAt without dwell",
                                 "unshifted ASCII letters/digits", "DOWN mapped by fixed upstream to slash",
                                 "bounded InputDevice transitions and source response boundaries"],
        "not_supported": ["general ACT-R", "arbitrary .cgt import", "UP/other function or modifier keys in integrated scope",
                          "nested menus/double click/general visual search", "active-attention frame reencoding", "full Vim/IME"],
        "reference_claim": "bounded observable implementation checks, not complete original GUI or human prediction accuracy",
    }


def run_example(out: str | Path) -> dict:
    """Copy and execute the bundled original Python single-click example."""
    from .io import export_result
    destination = Path(out)
    if destination.exists():
        raise ModelError(f"example output: choose a new directory: {destination}")
    # Read installed data through package resources, independent of cwd.
    payload = files("cogtool_py").joinpath("resources", "single_click.json").read_bytes()
    destination.mkdir(parents=True)
    path = destination / "single_click.json"
    path.write_bytes(payload)
    result = run_project(path, engine="klm_baseline")
    export_result(result, destination / "prediction")
    return {"input": str(path), "output": str(destination / "prediction"),
            "predicted_time_s": result.data["predicted_time_s"], "engine": "klm_baseline"}
