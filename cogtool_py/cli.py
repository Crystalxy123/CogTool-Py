"""Command-line entry point; importing the package starts no application."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .engine import predict
from .io import export_result, input_hash, load_project, save_project, write_json
from .models import ModelError
from .runtime import require_configuration, run_example, software_info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CogTool-Py: offline serial baseline and explicit bounded 2014 experimental engine")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "predict", "roundtrip"):
        sub = commands.add_parser(name)
        sub.add_argument("project", type=Path)
        if name != "validate":
            sub.add_argument("--out", type=Path, required=True)
        if name == "predict":
            sub.add_argument("--task")
        if name in {"predict", "validate"}:
            sub.add_argument("--engine", help="Assert the engine saved in the input; never change it implicitly")
            sub.add_argument("--scope", choices=["prefix_only", "integrated_task"], help="Assert the saved control scope")
            sub.add_argument("--run-policy", choices=["legacy_bounded", "reference_2014"], help="Assert the saved policy")
    info = commands.add_parser("info", help="Show distinct package/engine/schema/policy versions and limits")
    info.add_argument("--json", action="store_true", help="Write machine-readable JSON only")
    example = commands.add_parser("example", help="Copy and actually run the bundled single-click baseline")
    example.add_argument("--out", type=Path, required=True)
    benchmark = commands.add_parser("benchmark", help="Recalculate inputs against frozen records (R1, no new original run)")
    benchmark.add_argument("manifest", type=Path)
    benchmark.add_argument("--out", type=Path, required=True)
    comparison = commands.add_parser("compare", help="compare a result with real upstream evidence")
    comparison.add_argument("result", type=Path)
    comparison.add_argument("reference", type=Path)
    comparison.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "info":
            info = software_info()
            if args.json:
                print(json.dumps(info, ensure_ascii=False, indent=2))
            else:
                print(f"CogTool-Py {__version__}; klm_baseline {info['engines']['klm_baseline']['version']}; integrated_task 0.6.0")
                print("Saved engine/configuration is authoritative. No automatic fallback. Python runtime dependencies: none.")
                print("Bounded 2014 mechanisms only; no general .cgt import or full ACT-R / human accuracy claim. Use info --json for scope.")
            return 0
        if args.command == "example":
            print(json.dumps(run_example(args.out), ensure_ascii=False, indent=2))
            return 0
        if args.command == "benchmark":
            from .benchmark import run_benchmarks
            report = run_benchmarks(args.manifest, args.out)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return report["exit_code"]
        if args.command == "compare":
            from .comparison import compare_results
            report = compare_results(args.result, args.reference)
            write_json(args.out, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 4 if report["comparison_status"] == "different" else 0
        project = load_project(args.project)
        if args.command in {"predict", "validate"}:
            require_configuration(project, engine=args.engine, scope=args.scope, run_policy=args.run_policy)
        if args.command == "validate":
            print(f"valid: {project.id}; tasks={len(project.tasks)}; engine={project.engine}; sha256={input_hash(project)}")
        elif args.command == "roundtrip":
            save_project(project, args.out)
            restored = load_project(args.out)
            if input_hash(project) != input_hash(restored):
                raise ModelError("roundtrip changed semantic model hash")
            print(f"roundtrip verified: {args.out}")
        else:
            result = predict(project, args.task)
            export_result(result, args.out)
            if result.data['predicted_time_s'] is None:
                print(f"{result.data['task_id']}: {result.data['completion_status']}; no full task time; "
                      f"{project.engine}; output={args.out}")
                return 3
            print(f"{result.data['task_id']}: {result.data['predicted_time_s']:.9f} s predicted; "
                  f"{project.engine}; original comparison=unverified; output={args.out}")
        return 0
    except (ModelError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
