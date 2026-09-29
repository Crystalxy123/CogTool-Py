"""Capture real commands, outputs, hashes, and Python-only example results.

Does not manufacture original results or update numerical regression expectations.
Rerunning replaces this script's named Python records.
"""
from pathlib import Path
import datetime
import hashlib
import json
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "validation" / "python"


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    commands = [
        ("pytest", [sys.executable, "-m", "pytest", "-q", "--junitxml", str(DEST / "pytest.xml")]),
        ("version", [sys.executable, "-m", "cogtool_py", "--version"]),
    ]
    for case in ("single_click", "text_entry", "two_page_wait", "explicit_operators"):
        commands.extend([
            ("validate_" + case, [sys.executable, "-m", "cogtool_py", "validate", f"examples/{case}.json"]),
            ("predict_" + case, [sys.executable, "-m", "cogtool_py", "predict", f"examples/{case}.json",
                                "--out", str(DEST / case)]),
        ])
    commands.append(("roundtrip", [sys.executable, "-m", "cogtool_py", "roundtrip", "examples/single_click.json",
                                   "--out", str(DEST / "roundtrip.json")]))
    runs = []
    for name, command in commands:
        started = time.perf_counter()
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
        record = {"name": name, "command": command, "cwd": str(ROOT), "returncode": result.returncode,
                  "wall_seconds": time.perf_counter() - started}
        for stream in ("stdout", "stderr"):
            content = getattr(result, stream)
            path = DEST / f"{name}.{stream}.txt"
            path.write_text(content, encoding="utf-8")
            record[stream] = {"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(content.encode()).hexdigest()}
        runs.append(record)
        print(f"{name}: exit {result.returncode}")
        if result.returncode:
            print(result.stdout)
            print(result.stderr)
    packages = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    (DEST / "installed_packages.txt").write_text(packages)
    evidence = {"evidence_kind": "python_only_validation", "original_results": "not obtained",
                "recorded_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "python": sys.version, "executable": sys.executable, "platform": platform.platform(),
                "commands": runs}
    (DEST / "run_manifest.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    return 1 if any(r["returncode"] for r in runs) else 0


if __name__ == "__main__":
    raise SystemExit(main())
