#!/usr/bin/env python3
"""Build the self-contained Apple Silicon desktop app. LGPL-2.1-or-later.

Added 2026-09-28. No installation, network access, signing identity, or publication
is performed. Existing deliverables are preserved unless --replace is supplied.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import uuid


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "dist" / "macos-en"
BUILD = ROOT / "build" / "macos"
EXAMPLES = ("single_click.json", "text_entry.json", "two_page_wait.json", "explicit_operators.json")
EXAMPLES_SOURCE = ROOT / "desktop" / "examples-en"

ICON_SWIFT = r'''
import AppKit
import Foundation
let destination = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let sizes = [(16,1),(16,2),(32,1),(32,2),(128,1),(128,2),(256,1),(256,2),(512,1),(512,2)]
for (points, scale) in sizes {
    let pixels = points * scale
    let image = NSImage(size: NSSize(width: pixels, height: pixels))
    image.lockFocus()
    let side = CGFloat(pixels)
    let box = NSRect(x: side * 0.055, y: side * 0.055, width: side * 0.89, height: side * 0.89)
    let background = NSBezierPath(roundedRect: box, xRadius: side * 0.20, yRadius: side * 0.20)
    NSGradient(starting: NSColor(calibratedRed: 0.08, green: 0.22, blue: 0.27, alpha: 1),
               ending: NSColor(calibratedRed: 0.12, green: 0.45, blue: 0.47, alpha: 1))!.draw(in: background, angle: 90)
    let attributes: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: side * 0.43, weight: .bold),
        .foregroundColor: NSColor.white,
        .kern: -side * 0.025
    ]
    let label = NSAttributedString(string: "CT", attributes: attributes)
    let dimensions = label.size()
    label.draw(at: NSPoint(x: (side - dimensions.width) / 2, y: (side - dimensions.height) / 2))
    NSColor(calibratedRed: 1, green: 0.72, blue: 0.35, alpha: 1).setFill()
    NSBezierPath(ovalIn: NSRect(x: side * 0.73, y: side * 0.72, width: side * 0.095, height: side * 0.095)).fill()
    image.unlockFocus()
    let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
    let suffix = scale == 2 ? "@2x" : ""
    try bitmap.representation(using: .png, properties: [:])!.write(to: destination.appendingPathComponent("icon_\(points)x\(points)\(suffix).png"))
}
'''


def command(args: list[str | Path], *, cwd: Path = ROOT, env: dict | None = None) -> str:
    args = [str(value) for value in args]
    print("+ " + " ".join(args), flush=True)
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if result.returncode:
        raise RuntimeError(f"Command exited {result.returncode}: {args[0]}")
    return result.stdout.strip()


def json_command(args: list[str | Path], *, cwd: Path, env: dict) -> dict:
    # Keep prediction output in the build report instead of flooding build logs.
    result = subprocess.run([str(value) for value in args], cwd=cwd, env=env,
                            text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"Engine check failed ({result.returncode}): {result.stderr or result.stdout}")
    return json.loads(result.stdout)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files() -> list[Path]:
    files: set[Path] = set()
    for name in ("LICENSE", "NOTICE.md", "README.md", "CHANGELOG.md", "pyproject.toml", "MANIFEST.in", "requirements-dev.txt"):
        path = ROOT / name
        if path.is_file():
            files.add(path)
    files.add(Path(__file__).resolve())
    verifier = ROOT / "scripts" / "verify_macos_app.py"
    if verifier.is_file():
        files.add(verifier)
    for directory, suffixes in (("cogtool_py", {".py", ".json"}), ("desktop", {".py", ".swift", ".spec", ".txt", ".json"}),
                                 ("LICENSES", {".txt"}), ("docs", {".md"}), ("examples", {".py", ".json"})):
        files.update(path for path in (ROOT / directory).rglob("*")
                     if path.is_file() and path.suffix in suffixes and "__pycache__" not in path.parts)
    return sorted(files)


def make_source_archive(destination: Path, version: str, files: list[Path]) -> None:
    # Stable ordering/metadata make the source archive deterministic for identical inputs.
    with destination.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as archive:
            for path in files:
                info = archive.gettarinfo(str(path), arcname=f"CogTool-{version}-source/{path.relative_to(ROOT)}")
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                with path.open("rb") as stream:
                    archive.addfile(info, stream)


def copy_licenses(destination: Path) -> None:
    destination.mkdir(parents=True)
    for name in ("LICENSE", "NOTICE.md"):
        shutil.copy2(ROOT / name, destination / name)
    shutil.copytree(ROOT / "LICENSES", destination / "upstream")
    python_license = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError(f"Python license not found: {python_license}")
    shutil.copy2(python_license, destination / "Python-LICENSE.txt")
    distribution = importlib.metadata.distribution("PyInstaller")
    candidates = [path for path in distribution.files or [] if str(path).endswith("COPYING.txt")]
    if not candidates:
        raise RuntimeError("Installed PyInstaller is missing COPYING.txt")
    shutil.copy2(distribution.locate_file(candidates[0]), destination / "PyInstaller-COPYING.txt")


def copy_native_licenses(dependency_report: Path, destination: Path) -> dict:
    """Preserve notices for Homebrew libraries pulled in by Python extensions."""
    roots = set()
    for entry in json.loads(dependency_report.read_text()):
        path = Path(entry["source"]).resolve()
        if "Cellar" in path.parts:
            index = path.parts.index("Cellar")
            roots.add(Path(*path.parts[:index + 3]))
    manifest = {}
    for root in sorted(roots):
        label = root.parent.name + "-" + root.name
        candidates = [path for path in root.iterdir() if path.is_file()
                      and path.name.upper().startswith(("LICENSE", "COPYING", "COPYRIGHT", "NOTICE"))]
        if not candidates:
            raise RuntimeError(f"No native dependency license found: {root}")
        folder = destination / label
        folder.mkdir(parents=True)
        for path in candidates:
            shutil.copy2(path, folder / path.name)
        manifest[label] = [path.name for path in candidates]
    return manifest


def check_engine(engine: Path, resources: Path, stage: Path, env: dict) -> dict:
    check_dir = stage / "checks"
    check_dir.mkdir()
    # Run frozen code away from the checkout with a deliberately minimal environment.
    isolated = {key: env[key] for key in ("HOME", "TMPDIR", "LANG") if key in env}
    isolated["PATH"] = "/usr/bin:/bin"
    frozen_info = json_command([engine, "info"], cwd=check_dir, env=isolated)
    reference_info = json_command([sys.executable, ROOT / "desktop" / "bridge.py", "info"], cwd=ROOT, env=env)
    if frozen_info != reference_info:
        raise RuntimeError("Frozen engine version/capability information differs from source")
    checked = []
    for example in EXAMPLES:
        input_path = resources / "Examples" / example
        inspection = json_command([engine, "inspect", input_path], cwd=check_dir, env=isolated)
        for task in inspection["project"]["tasks"]:
            name = f"{Path(example).stem}-{task['id']}"
            actual = json_command([engine, "predict", input_path, "--task", task["id"], "--out", check_dir / f"frozen-{name}"],
                                  cwd=check_dir, env=isolated)["result"]
            expected = json_command([sys.executable, ROOT / "desktop" / "bridge.py", "predict", input_path,
                                     "--task", task["id"], "--out", check_dir / f"source-{name}"], cwd=ROOT, env=env)["result"]
            if not actual.get("implementation", {}).get("files"):
                raise RuntimeError("Frozen engine implementation fingerprint has no source files")
            actual.pop("program_runtime_s", None)
            expected.pop("program_runtime_s", None)
            if actual != expected:
                raise RuntimeError(f"Frozen/source prediction mismatch: {name}")
            checked.append({"example": example, "task_id": task["id"], "predicted_time_s": actual["predicted_time_s"],
                            "implementation_sha256": actual["implementation"]["sha256"], "source_result_equal": True})
    # Also check importlib.resources in the public CLI, independently of GUI examples.
    json_command([engine, "--cli", "example", "--out", check_dir / "public-example"], cwd=check_dir, env=isolated)
    return {"software_info_equal": True, "examples": checked, "public_example_passed": True,
            "external_python_on_path": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", action="store_true", help="Replace only this version's named desktop deliverables after a successful build")
    args = parser.parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64":
        parser.error("This build recipe requires macOS on Apple Silicon (arm64).")
    if sys.version_info < (3, 11):
        parser.error("Build with Python 3.11 or later.")
    version_match = re.search(r'^__version__ = "([^"]+)"', (ROOT / "cogtool_py" / "__init__.py").read_text(), re.M)
    if version_match is None:
        raise RuntimeError("Cannot read project version")
    version = version_match.group(1)
    names = ["CogTool.app", f"CogTool-{version}-macOS-arm64-English.dmg", f"CogTool-{version}-macOS-arm64-English.zip",
             f"CogTool-{version}-source-English.tar.gz", f"CogTool-{version}-build-report-English.json"]
    existing = [OUTPUT / name for name in names if (OUTPUT / name).exists() or (OUTPUT / name).is_symlink()]
    if existing and not args.replace:
        parser.error("Existing output preserved; pass --replace to rebuild: " + ", ".join(str(path) for path in existing))
    dependencies = {}
    for line in (ROOT / "desktop" / "macos" / "requirements-build.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, required = line.split("==")
        actual = importlib.metadata.version(name)
        if actual != required:
            raise RuntimeError(f"Build dependency mismatch: {name} expected {required}, installed {actual}")
        dependencies[name] = actual
    for required in (ROOT / "desktop" / "bridge.py", ROOT / "desktop" / "macos" / "CogToolApp.swift",
                     ROOT / "docs" / "MAC_APP_en.md", *(EXAMPLES_SOURCE / name for name in EXAMPLES)):
        if not required.is_file():
            raise RuntimeError(f"Missing source: {required}")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    stage = BUILD / "runs" / run_id
    stage.mkdir(parents=True)
    cache = BUILD / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    sdk = command(["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-path"])
    env = os.environ.copy()
    env.update({"PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1", "MACOSX_DEPLOYMENT_TARGET": "15.0",
                "SDKROOT": sdk, "CLANG_MODULE_CACHE_PATH": str(cache / "clang"),
                "SWIFT_MODULECACHE_PATH": str(cache / "swift"), "PYINSTALLER_CONFIG_DIR": str(cache / "pyinstaller")})
    command([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", stage / "frozen",
             "--workpath", stage / "pyinstaller", ROOT / "desktop" / "macos" / "engine.spec"], env=env)
    app = stage / "CogTool.app"
    contents = app / "Contents"
    executable_dir = contents / "MacOS"
    resources = contents / "Resources"
    executable_dir.mkdir(parents=True)
    resources.mkdir()
    shutil.copytree(stage / "frozen" / "cogtool-engine", resources / "engine", symlinks=True)
    examples = resources / "Examples"
    examples.mkdir()
    for name in EXAMPLES:
        shutil.copy2(EXAMPLES_SOURCE / name, examples / name)
    copy_licenses(resources / "Licenses")
    native_licenses = copy_native_licenses(stage / "pyinstaller" / "engine" / "native-dependencies.json",
                                          resources / "Licenses" / "native")
    shutil.copy2(ROOT / "docs" / "MAC_APP_en.md", resources / "English User Guide.md")
    files = source_files()
    source_archive = stage / f"CogTool-{version}-source-English.tar.gz"
    make_source_archive(source_archive, version, files)
    (resources / "Source").mkdir()
    shutil.copy2(source_archive, resources / "Source" / source_archive.name)
    checks = check_engine(resources / "engine" / "cogtool-engine", resources, stage, env)
    compiler = ["/usr/bin/xcrun", "--sdk", "macosx", "swiftc", "-sdk", sdk,
                "-target", "arm64-apple-macosx15.0", "-module-cache-path", str(cache / "swift")]
    command([*compiler, "-O", "-parse-as-library", ROOT / "desktop" / "macos" / "CogToolApp.swift",
             "-o", executable_dir / "CogTool"], env=env)
    icon_source = stage / "Icon.swift"
    icon_source.write_text(ICON_SWIFT)
    iconset = stage / "CogTool.iconset"
    iconset.mkdir()
    command([*compiler, icon_source, "-o", stage / "render-icon"], env=env)
    command([stage / "render-icon", iconset], env=env)
    command(["/usr/bin/iconutil", "-c", "icns", iconset, "-o", resources / "CogTool.icns"], env=env)
    info = {"CFBundleExecutable": "CogTool", "CFBundleIdentifier": "org.cogtoolpy.desktop",
            "CFBundleName": "CogTool", "CFBundleDisplayName": "CogTool", "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": re.match(r"\d+\.\d+\.\d+", version).group(),
            "CFBundleVersion": "1", "CFBundleIconFile": "CogTool.icns", "LSMinimumSystemVersion": "15.0",
            "NSHighResolutionCapable": True, "NSPrincipalClass": "NSApplication",
            "NSHumanReadableCopyright": "CogTool-Py desktop, LGPL-2.1-or-later. See Resources/Licenses/NOTICE.md.",
            "LSApplicationCategoryType": "public.app-category.education"}
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)
    (contents / "PkgInfo").write_bytes(b"APPL????")
    report = {"version": version, "interface_language": "en", "built_at_utc": datetime.now(timezone.utc).isoformat(),
              "architecture": "arm64", "minimum_macos": "15.0", "build_macos": platform.mac_ver()[0],
              "python": sys.version, "swift": command(["/usr/bin/swift", "--version"]), "sdk": sdk,
              "build_dependencies": dependencies, "signature": "ad-hoc; no Developer ID or notarization",
              "native_dependency_licenses": native_licenses,
              "checks": checks, "source_files": {str(path.relative_to(ROOT)): sha256(path) for path in files},
              "source_archive_sha256": sha256(source_archive), "build_workspace": str(stage)}
    (resources / "build-manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    command(["/usr/bin/codesign", "--verify", "--strict", resources / "engine" / "cogtool-engine"])
    command(["/usr/bin/codesign", "--force", "--sign", "-", app])
    command(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    dmg_stage = stage / "disk-image"
    dmg_stage.mkdir()
    shutil.copytree(app, dmg_stage / app.name, symlinks=True)
    (dmg_stage / "Applications").symlink_to("/Applications")
    dmg = stage / f"CogTool-{version}-macOS-arm64-English.dmg"
    command(["/usr/bin/hdiutil", "create", "-volname", "CogTool English", "-srcfolder", dmg_stage,
             "-format", "UDZO", "-fs", "HFS+", dmg])
    command(["/usr/bin/hdiutil", "verify", dmg])
    zip_path = stage / f"CogTool-{version}-macOS-arm64-English.zip"
    command(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, zip_path])
    report["artifacts"] = {path.name: {"sha256": sha256(path), "bytes": path.stat().st_size}
                           for path in (dmg, zip_path, source_archive)}
    report["checks"].update({"codesign_verified": True, "dmg_verified": True})
    report_path = stage / f"CogTool-{version}-build-report-English.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Replacement happens only after a complete, verified build. No general dist cleanup.
    for name in names:
        destination = OUTPUT / name
        if destination.exists() or destination.is_symlink():
            if not args.replace:
                raise RuntimeError(f"Output appeared during build; preserved: {destination}")
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        shutil.move(str(stage / name), str(destination))
    print(f"Built: {OUTPUT / 'CogTool.app'}\nInstaller: {OUTPUT / dmg.name}\nReport: {OUTPUT / report_path.name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, importlib.metadata.PackageNotFoundError) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
