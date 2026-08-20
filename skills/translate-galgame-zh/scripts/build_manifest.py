#!/usr/bin/env python3
"""Create a stable SHA-256 manifest for an original game directory."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    source = args.source_dir.resolve()
    if not source.is_dir():
        parser.error(f"source directory does not exist: {source}")

    paths = sorted(
        (path for path in source.rglob("*") if path.is_file() and not path.is_symlink()),
        key=lambda path: path.relative_to(source).as_posix().casefold(),
    )
    entries = []
    for path in paths:
        stat = path.stat()
        entries.append(
            {
                "path": path.relative_to(source).as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(path),
            }
        )

    canonical = json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    manifest = {
        "schema_version": 1,
        "source_dir": str(source),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(entries),
        "total_bytes": sum(item["size"] for item in entries),
        "entries_sha256": hashlib.sha256(canonical).hexdigest(),
        "files": entries,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "file_count": len(entries),
                "total_bytes": manifest["total_bytes"],
                "entries_sha256": manifest["entries_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
