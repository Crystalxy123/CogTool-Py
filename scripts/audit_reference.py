"""Verify exported reference bytes against existing immutable Git objects."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ("cogtool", "upstream-cogtool", "https://github.com/cogtool/cogtool",
     "a91d91e8dcf95d762b6e08020029a36ea079bbba", "1.3-2014-02-10"),
    ("documentation", "upstream-documentation", "https://github.com/cogtool/documentation",
     "1f5fe10e2bebfb7544aa85a6db2c10078df9f9d3", "master at recorded commit"),
]


def main() -> None:
    records = []
    for local, export, url, commit, ref in SOURCES:
        tree = subprocess.check_output(["git", "-C", str(ROOT / local), "ls-tree", "-rz", commit])
        files = []
        for entry in tree.split(b"\0"):
            if not entry:
                continue
            meta, name = entry.split(b"\t", 1)
            mode, kind, expected = meta.decode().split()
            if kind != "blob":
                raise RuntimeError(f"unhandled reference object: {meta}")
            path = ROOT / "reference" / export / name.decode()
            content = os.readlink(path).encode() if mode == "120000" else path.read_bytes()
            blob_sha = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
            if blob_sha != expected:
                raise RuntimeError(f"reference differs from commit: {path}")
            files.append({"path": name.decode(), "git_blob": expected,
                          "sha256": hashlib.sha256(content).hexdigest()})
        records.append({"repository": url, "commit": commit, "ref": ref,
                        "acquisition": "git archive from user's pre-existing Git objects; excludes working-tree modifications",
                        "export_date": "2026-09-24", "local_directory": "reference/" + export,
                        "verified_files": len(files), "files": files})
    payload = {"schema_version": 1, "verified_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "sources": records, "remote_head_claim": False,
               "remote_attempts": ["sandboxed git ls-remote: Could not resolve host: github.com",
                                   "network-enabled retry: CogTool HTTP2 framing error; documentation port 443 connection timeout; no remote HEAD claimed"],
               "user_original_directories": "preserved; exports checked against commits, not dirty working trees"}
    destination = ROOT / "reference" / "manifest.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    for record in records:
        print(f"{record['repository']}@{record['commit']}: {record['verified_files']} blobs match")


if __name__ == "__main__":
    main()
