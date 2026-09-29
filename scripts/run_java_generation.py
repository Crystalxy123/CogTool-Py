"""Compile fixed upstream Git objects and independently run the real Java frontend.

Python only starts processes, copies files and records hashes. It never parses
the input project, constructs cognitive steps, or writes Lisp model content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "a91d91e8dcf95d762b6e08020029a36ea079bbba"
SWT_SHA = "d08b3446a5ca524f0a56c70b1fb715c8dca20eb0a30bb6aa33a061ff4b87b562"
SWT_URL = "https://repo.maven.apache.org/maven2/org/eclipse/platform/org.eclipse.swt.cocoa.macosx.aarch64/3.132.0/org.eclipse.swt.cocoa.macosx.aarch64-3.132.0.jar"
MAIN = "org.cogtoolvalidation.JavaGenerationMain"
FACTORY = "org.cogtoolvalidation.SourceDefaultPreferencesFactory"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def read(path):
    return json.loads(path.read_text())


def fresh(path):
    if path.exists():
        raise FileExistsError("Refusing to overwrite evidence: " + str(path))
    path.mkdir(parents=True)


def command(out, name, argv, timeout=120, binary_stdout=None):
    logs = out / "logs"
    logs.mkdir(exist_ok=True)
    if (logs / (name + ".json")).exists():
        raise FileExistsError(name)
    started = time.perf_counter()
    try:
        process = subprocess.run(list(map(str, argv)), cwd=ROOT, capture_output=True, timeout=timeout)
        code, stdout, stderr = process.returncode, process.stdout, process.stderr
    except subprocess.TimeoutExpired as exc:
        code, stdout, stderr = 124, exc.stdout or b"", (exc.stderr or b"") + b"\nTIMEOUT"
    except OSError as exc:
        code, stdout, stderr = 127, b"", str(exc).encode()
    if binary_stdout is not None:
        binary_stdout.write_bytes(stdout)
    else:
        (logs / (name + ".stdout.txt")).write_bytes(stdout)
    (logs / (name + ".stderr.txt")).write_bytes(stderr)
    record = {"command": list(map(str, argv)), "cwd": str(ROOT), "timeout_s": timeout,
              "returncode": code, "wall_clock_runtime_s": time.perf_counter() - started,
              "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
              "stderr_sha256": hashlib.sha256(stderr).hexdigest()}
    write(logs / (name + ".json"), record)
    print(name + ": exit " + str(code), flush=True)
    if code:
        raise RuntimeError(name + " failed; see " + str(logs))
    return record


def file_hashes(directory):
    return {str(p.relative_to(directory)): sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}


def build(out, repository, swt_jar):
    if sha(swt_jar) != SWT_SHA:
        raise ValueError("SWT dependency differs from the independently downloaded and recorded artifact")
    fresh(out)
    archive = out / "upstream-source.tar"
    command(out, "git_archive", ["git", "-C", repository, "archive", COMMIT,
                                 "java", "lib", "mac-support", "build.xml", "LICENSE.txt"], binary_stdout=archive)
    source = out / "source"
    source.mkdir()
    with tarfile.open(archive) as content:
        content.extractall(source, filter="data")
    source_hashes = file_hashes(source)
    command(out, "java_version", ["java", "-version"])
    command(out, "javac_version", ["javac", "-version"])
    classes = out / "classes"
    classes.mkdir()
    old_jars = [source / "lib/macintosh/swt.jar", source / "lib/windows/swt.jar"] + sorted((source / "lib").glob("*.jar"))
    compile_classpath = os.pathsep.join(map(str, old_jars))
    files = sorted((source / "java").rglob("*.java")) + sorted((source / "mac-support").rglob("*.java"))
    source_list = out / "source_files.txt"
    source_list.write_text("\n".join(map(str, files)) + "\n")
    command(out, "compile_upstream", ["javac", "--release", "8", "-encoding", "UTF-8",
                                     "-classpath", compile_classpath, "-d", classes, "@" + str(source_list)])
    harness = out / "harness"
    shutil.copytree(ROOT / "scripts/java", harness)
    command(out, "compile_harness", ["javac", "--release", "8", "-encoding", "UTF-8",
                                    "-classpath", str(classes) + os.pathsep + compile_classpath, "-d", classes,
                                    *sorted(harness.rglob("*.java"))])
    resource = Path("edu/cmu/cs/hcii/cogtool/resources")
    shutil.copytree(source / "java" / resource, classes / resource, dirs_exist_ok=True)
    dependencies = out / "dependencies"
    dependencies.mkdir()
    dependency = dependencies / swt_jar.name
    shutil.copyfile(swt_jar, dependency)
    native = dependencies / "native"
    native.mkdir()
    with zipfile.ZipFile(dependency) as content:
        for name in content.namelist():
            if name.endswith((".jnilib", ".dylib")):
                (native / Path(name).name).write_bytes(content.read(name))
    runtime_cp = os.pathsep.join(map(str, [dependency, classes, *old_jars]))
    (out / "classpath.txt").write_text(runtime_cp + "\n")
    unchanged = source_hashes == file_hashes(source)
    if not unchanged:
        raise RuntimeError("Exported upstream source changed during compilation")
    manifest = {"source_commit": COMMIT, "archive_sha256": sha(archive), "source_hashes": source_hashes,
                "harness_hashes": file_hashes(harness), "class_and_resource_hashes": file_hashes(classes),
                "swt": {"url": SWT_URL, "sha256": sha(dependency), "version": "3.132.0",
                        "kind": "real Eclipse SWT Cocoa macOS aarch64", "native_hashes": file_hashes(native)},
                "classpath": runtime_cp, "native_directory": str(native), "upstream_source_patches": [],
                "build_adaptations": ["JDK26 --release 8 instead of obsolete Java 1.5 compile target"],
                "platform_adaptations": ["Real current SWT Cocoa ARM64 precedes original SWT jars at runtime",
                                         "Extract unmodified native libraries from the same SWT artifact",
                                         "Run on first macOS thread with native access and real WindowServer access"],
                "configuration_policy": "Explicit isolated in-memory source-default preferences; no host preferences",
                "upstream_sources_preserved": unchanged}
    write(out / "build_manifest.json", manifest)
    return manifest


def verify_build(directory):
    m = read(directory / "build_manifest.json")
    if "base_build_directory" in m:
        base = Path(m["base_build_directory"])
        verify_build(base)
        checks = {
            "base_manifest": sha(base / "build_manifest.json") == m["base_build_manifest_sha256"],
            "harness": file_hashes(directory / "harness") == m["harness_hashes"],
            "classes": file_hashes(directory / "classes") == m["class_and_resource_hashes"],
        }
        if not all(checks.values()):
            raise ValueError("Harness overlay identity verification failed: " + str(checks))
        return m
    checks = {"source": file_hashes(directory / "source") == m["source_hashes"],
              "harness": file_hashes(directory / "harness") == m["harness_hashes"],
              "classes": file_hashes(directory / "classes") == m["class_and_resource_hashes"],
              "native": file_hashes(Path(m["native_directory"])) == m["swt"]["native_hashes"],
              "swt": sha(Path(m["classpath"].split(os.pathsep)[0])) == m["swt"]["sha256"]}
    if not all(checks.values()):
        raise ValueError("Build identity verification failed: " + str(checks))
    return m


def extend_harness(base_directory, out):
    """Compile only the new harness; reuse all frozen upstream classes/native code."""
    base = verify_build(base_directory)
    fresh(out)
    harness, classes = out / "harness", out / "classes"
    shutil.copytree(ROOT / "scripts/java", harness)
    classes.mkdir()
    command(out, "compile_harness_overlay", ["javac", "--release", "8", "-encoding", "UTF-8",
                                            "-classpath", base["classpath"], "-d", classes,
                                            *sorted(harness.rglob("*.java"))])
    manifest = {
        "source_commit": COMMIT, "base_build_directory": str(base_directory),
        "base_build_manifest_sha256": sha(base_directory / "build_manifest.json"),
        "harness_hashes": file_hashes(harness), "class_and_resource_hashes": file_hashes(classes),
        "classpath": str(classes) + os.pathsep + base["classpath"],
        "native_directory": base["native_directory"], "swt": base["swt"],
        "upstream_source_patches": [], "upstream_classes_recompiled": False,
        "adaptation": "New synthetic high-level Java object builder and observer only; frozen original code reused.",
    }
    verify_build(base_directory)
    write(out / "build_manifest.json", manifest)
    return manifest


def generate(build_directory, original, selector, case_id, out, repetitions, *, synthetic=False):
    m = verify_build(build_directory)
    original_hash = sha(original)
    fresh(out)
    config = out / "source_defaults.properties"
    config.write_text("preference_policy=source_defaults\ncase_id=" + case_id + "\n")
    repetitions_data = []
    for index in range(1, repetitions + 1):
        destination = out / ("generation_" + str(index))
        temp = out / ("java_tmp_" + str(index))
        temp.mkdir()
        classes_log = out / ("generation_" + str(index) + ".classes.log")
        cmd = ["java", "-XstartOnFirstThread", "--enable-native-access=ALL-UNNAMED",
               "-Djava.util.prefs.PreferencesFactory=" + FACTORY, "-Djava.io.tmpdir=" + str(temp),
               "-Dswt.library.path=" + m["native_directory"], "-Djava.library.path=" + m["native_directory"],
               "-Xlog:class+load=info:file=" + str(classes_log), "-classpath", m["classpath"],
               MAIN, *(["--synthetic", original] if synthetic else [original, selector]), config, destination]
        command(out, "generation_" + str(index), cmd)
        record = read(destination / "generation_record.json")
        if not (record["fresh_regeneration_verified"] is True and record["original_input_sha256"] == original_hash):
            raise ValueError("Generation evidence does not establish fresh original-project generation")
        if any(record[key] is not False for key in ("raw_reader_shared", "step_generator_shared", "lisp_writer_shared")):
            raise ValueError("Unexpected shared frontend component")
        repetitions_data.append({"output": str(destination), "model_sha256": sha(destination / "model.lisp"),
                                 "record_sha256": sha(destination / "generation_record.json"),
                                 "fresh_step_count": record["fresh_step_count"],
                                 "files": file_hashes(destination), "class_load_log_sha256": sha(classes_log)})
    same_raw = len({row["model_sha256"] for row in repetitions_data}) == 1
    observed_files = ("original_scene.json", "original_demonstration.json", "cached_steps.json",
                      "fresh_steps.json", "preferences.json", "generator_warnings.json")
    observer_equal = {name: len({row["files"][name] for row in repetitions_data}) == 1 for name in observed_files}
    verify_build(build_directory)
    if sha(original) != original_hash:
        raise ValueError("Original project file changed")
    summary = {"case_id": case_id, "status": "PASS" if same_raw and all(observer_equal.values()) else "DIFFERENT",
               "source_commit": COMMIT, "independent_process_count": repetitions, "repetitions": repetitions_data,
               "raw_lisp_bytes_identical": same_raw, "ordered_observation_files_identical": observer_equal,
               "semantic_normalization": "none: exact raw Lisp bytes and ordered observations; no sorting or ID rewriting",
               "input_sha256": original_hash, "original_preserved": True, "build_identity_preserved": True,
               "build_manifest_sha256": sha(build_directory / "build_manifest.json"),
               "preference_policy": "source_defaults", "original_rerun_s": None,
               "case_origin": "synthetic" if synthetic else "official_original_project",
               "high_level_spec_shared": synthetic, "official_cgt_reader_executed": not synthetic,
               "accuracy_or_full_original_application_claim": False}
    write(out / "summary.json", summary)
    return 0 if summary["status"] == "PASS" else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="operation", required=True)
    b = sub.add_parser("build")
    b.add_argument("--repository", type=Path, default=ROOT / "cogtool")
    b.add_argument("--swt-jar", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    e = sub.add_parser("extend-harness", help="Reuse frozen original build; compile only current Java harness")
    e.add_argument("--base-build", type=Path, required=True)
    e.add_argument("--out", type=Path, required=True)
    g = sub.add_parser("generate")
    g.add_argument("--build", type=Path, required=True)
    g.add_argument("--original", type=Path, required=True)
    g.add_argument("--selector", required=True, help="Exact original Design::Task names")
    g.add_argument("--case-id", required=True, help="Evidence label, not used by CogTool generation")
    g.add_argument("--preference-policy", choices=["source_defaults"], required=True)
    g.add_argument("--out", type=Path, required=True)
    g.add_argument("--repetitions", type=int, default=2)
    s = sub.add_parser("generate-synthetic", help="Original Java objects from shared high-level XML spec")
    s.add_argument("--build", type=Path, required=True)
    s.add_argument("--spec", type=Path, required=True)
    s.add_argument("--case-id", required=True)
    s.add_argument("--preference-policy", choices=["source_defaults"], required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--repetitions", type=int, default=2)
    a = p.parse_args(argv)
    if a.operation == "build":
        build(a.out.resolve(), a.repository.resolve(), a.swt_jar.resolve())
        return 0
    if a.operation == "extend-harness":
        extend_harness(a.base_build.resolve(), a.out.resolve())
        return 0
    if a.repetitions < 2 or a.repetitions > 3:
        p.error("bounded generation requires 2 or 3 independent processes")
    if "\n" in a.case_id or "\r" in a.case_id:
        p.error("case-id must be one line")
    if a.operation == "generate-synthetic":
        return generate(a.build.resolve(), a.spec.resolve(), None, a.case_id, a.out.resolve(),
                        a.repetitions, synthetic=True)
    return generate(a.build.resolve(), a.original.resolve(), a.selector, a.case_id, a.out.resolve(), a.repetitions)


if __name__ == "__main__":
    raise SystemExit(main())
