# CogTool desktop bridge, LGPL-2.1-or-later. Added 2026-09-28.
# Keep source alongside bytecode: implementation_fingerprint hashes these bytes.
from pathlib import Path
import json
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).resolve().parents[1]
package = root / "cogtool_py"
source_data = [(str(path), str(path.parent.relative_to(root)))
               for path in sorted(package.rglob("*"))
               if path.is_file() and path.suffix in {".py", ".json"}
               and "__pycache__" not in path.parts]

a = Analysis(
    [str(root / "desktop" / "bridge.py")],
    pathex=[str(root)],
    binaries=[],
    datas=source_data,
    hiddenimports=collect_submodules("cogtool_py"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pytest"],
    noarchive=False,
)
Path(workpath, "native-dependencies.json").write_text(json.dumps(
    [{"name": name, "source": source} for name, source, kind in a.binaries], indent=2))
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="cogtool-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
    contents_directory="_internal",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="cogtool-engine")
