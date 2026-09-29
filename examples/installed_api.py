"""Run a saved input using installed public APIs, with an explicit engine check.

Usage: python examples/installed_api.py INPUT_JSON OUTPUT_DIRECTORY
No research scripts, test helpers, Java or Lisp are imported.
"""
from pathlib import Path
import sys

from cogtool_py.engine import predict
from cogtool_py.io import export_result, load_project
from cogtool_py.runtime import require_configuration


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: installed_api.py INPUT_JSON OUTPUT_DIRECTORY")
    project = load_project(Path(sys.argv[1]))
    require_configuration(project, engine="klm_baseline")
    result = predict(project)
    export_result(result, Path(sys.argv[2]))
    print(f"{result.data['predicted_time_s']:.9f} s predicted; engine={project.engine}")


if __name__ == "__main__":
    main()
