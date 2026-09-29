"""JSON-only process boundary for the native desktop application.

The desktop delegates to the existing public model and prediction APIs. It does
not choose a different engine, alter parameters, or interpret a partial run as a
complete prediction. Each calculation owns a new output directory.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from cogtool_py.engine import predict
from cogtool_py.io import export_result, input_hash, load_project, save_project
from cogtool_py.models import ModelError
from cogtool_py.runtime import require_configuration, software_info


def inspect_project(path: Path) -> dict:
    project = require_configuration(load_project(path))
    return {
        "id": project.id,
        "name": project.name,
        "engine": project.engine,
        "tasks": [
            {"id": task.id, "name": task.name,
             "step_count": len(task.demonstration.steps)}
            for task in project.tasks
        ],
        "frame_count": len(project.design.frames),
        "scope": project.control.execution_scope if project.control else None,
        "run_policy": project.control.run_policy if project.control else None,
        "input_sha256": input_hash(project),
    }


def run_prediction(path: Path, task_id: str, output: Path) -> tuple[dict, int]:
    project = require_configuration(load_project(path))
    # Validate the selected task before doing any work or creating output files.
    if task_id not in {task.id for task in project.tasks}:
        raise ModelError(f"Unknown task: {task_id}")
    output = output.expanduser().resolve()
    if output.exists():
        raise ModelError(f"Output directory already exists. Choose a new directory to preserve previous results: {output}")
    result = predict(project, task_id)
    # mkdir without exist_ok also closes a race with another app instance.
    output.mkdir(parents=True, exist_ok=False)
    save_project(project, output / "input.json")
    export_result(result, output)
    return {"ok": True, "result": result.data, "output_dir": str(output)}, (
        0 if result.data["predicted_time_s"] is not None else 3
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--cli"]:
        from cogtool_py.cli import main as cli_main
        return cli_main(argv[1:])
    parser = argparse.ArgumentParser(description="CogTool desktop calculation bridge")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("path", type=Path)
    run = commands.add_parser("predict")
    run.add_argument("path", type=Path)
    run.add_argument("--task", required=True)
    run.add_argument("--out", type=Path, required=True)
    commands.add_parser("info")
    args = parser.parse_args(argv)
    try:
        status = 0
        if args.command == "inspect":
            payload = {"ok": True, "project": inspect_project(args.path)}
        elif args.command == "predict":
            payload, status = run_prediction(args.path, args.task, args.out)
        else:
            payload = {"ok": True, "software": software_info()}
    except (ModelError, OSError, ValueError, RecursionError) as exc:
        payload, status = {"ok": False, "error": str(exc)}, 2
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
