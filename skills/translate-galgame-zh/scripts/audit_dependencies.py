#!/usr/bin/env python3
"""List reusable and dirty job snapshots without changing job statuses."""
import argparse
import json
import sys
from pathlib import Path
sys.dont_write_bytecode = True
from pipeline_common import atomic_text, json_text, read_jsonl, read_snapshot, validate_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    project = args.project_root.resolve()
    try:
        with read_snapshot():
            jobs = read_jsonl(project / "planning/jobs.jsonl")
            records = [{"job_id": job["job_id"], "issues": validate_bundle(project, job)} for job in jobs]
        result = {"schema_version": 1, "reusable": [x["job_id"] for x in records if not x["issues"]],
                  "needs_attention": [x for x in records if x["issues"]], "mutated_jobs": False}
        if args.report:
            atomic_text(args.report.resolve(), json_text(result))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["needs_attention"] else 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
