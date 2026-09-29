"""Versioned JSON persistence and auditable result exports."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .models import ModelError, Project


def read_json(path: str | Path) -> Any:
    def constant(value: str) -> None:
        raise ModelError(f"{path}: non-finite JSON constant {value!r} is forbidden")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ModelError(f"{path}: duplicate JSON field {key!r}")
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=constant, object_pairs_hook=unique_pairs)
    except ModelError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise ModelError(f"{path}: {exc}") from exc


def load_project(path: str | Path) -> Project:
    from .generator import validate
    project = Project.from_dict(read_json(path))
    validate(project)
    return project


def write_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        f.write(payload)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def save_project(project: Project, path: str | Path) -> None:
    from .validation import validate_project
    # Validate actual objects before serialization, which can otherwise omit an
    # invalid field and accidentally repair an unsupported direct API object.
    validate_project(project)
    write_json(path, project.to_dict())


def input_hash(project: Project) -> str:
    from .validation import validate_project
    validate_project(project)
    canonical = json.dumps(project.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def implementation_fingerprint() -> dict[str, Any]:
    """Identify executed package sources separately from semantic model content.

    Includes installed Python source bytes instead of relying on a possibly
    unchanged release string or on a Git checkout being available.
    """
    from . import ENGINE_VERSION, UPSTREAM_COMMIT, __version__
    package = Path(__file__).resolve().parent
    try:
        files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in sorted(package.glob("*.py"))}
    except OSError as exc:
        raise ModelError(f"implementation identity: cannot read package sources: {exc}") from exc
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return {"algorithm": "sha256", "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "files": files, "software_version": __version__, "engine_version": ENGINE_VERSION,
            "upstream_commit": UPSTREAM_COMMIT}


def export_result(result: Any, directory: str | Path) -> tuple[Path, Path, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    data = result.to_dict() if hasattr(result, "to_dict") else result
    result_path, event_path, step_path = (directory / name for name in ("result.json", "events.csv", "steps.csv"))
    write_json(result_path, data)
    for path, rows, fields in [
        (event_path, data["events"], ["index", "step_index", "demo_index", "op", "origin", "resource", "start_s", "end_s", "duration_s"]),
        (step_path, data["steps"], ["index", "demo_index", "op", "origin", "frame", "target", "key", "device", "duration_s", "source", "note"]),
    ]:
        # Preserve the legacy leading columns while retaining real controller,
        # state and provenance fields rather than silently discarding them.
        fields = list(dict.fromkeys([*fields, *(key for row in rows for key in row)]))
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows({key: json.dumps(value, ensure_ascii=False, allow_nan=False)
                             if isinstance(value, (dict, list, tuple)) else value
                             for key, value in row.items()} for row in rows)
    for key in ("motor_events", "vision_events"):
        if key in data:
            rows = data[key]
            fields = list(dict.fromkeys(k for row in rows for k in row))
            with (directory / (key + ".csv")).open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows({k: json.dumps(v, ensure_ascii=False, allow_nan=False)
                                  if isinstance(v, (dict, list, tuple)) else v for k, v in row.items()} for row in rows)
    return result_path, event_path, step_path
