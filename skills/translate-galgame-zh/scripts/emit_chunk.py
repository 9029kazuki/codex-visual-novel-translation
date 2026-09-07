#!/usr/bin/env python3
"""Emit exactly one validated model packet; full plans remain machine-side."""
import argparse
import json
import sys
from pathlib import Path
sys.dont_write_bytecode = True
from pipeline_common import bundle_dir, digest_text, inside, read_json, read_text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("job_id")
    parser.add_argument("chunk_id")
    args = parser.parse_args()
    try:
        root = bundle_dir(args.project_root.resolve(), args.job_id)
        status = read_json(root / "bundle-status.json")
        plan_text = read_text(root / "chunk-plan.json")
        if digest_text(plan_text) != status["artifacts"]["chunk-plan.json"]:
            raise ValueError("chunk plan digest mismatch")
        matches = [x for x in json.loads(plan_text)["chunks"] if x["chunk_id"] == args.chunk_id]
        if len(matches) != 1:
            raise ValueError("unknown or duplicate chunk ID")
        path = matches[0]["packet"]
        packet = read_text(inside(root, path))
        if digest_text(packet) != status["artifacts"][path]:
            raise ValueError("packet digest mismatch")
        print(packet, end="")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
