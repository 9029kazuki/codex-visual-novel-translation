#!/usr/bin/env python3
"""Atomically update one job in planning/jobs.jsonl."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUSES = (
    "pending",
    "assigned",
    "translated",
    "validated",
    "reviewed",
    "approved",
    "merged",
    "failed",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs_jsonl", type=Path)
    parser.add_argument("job_id")
    parser.add_argument("status", choices=STATUSES)
    parser.add_argument("--from-status", choices=STATUSES)
    parser.add_argument("--worker")
    parser.add_argument("--reviewer")
    parser.add_argument("--note")
    parser.add_argument("--also-job", action="append", default=[], help="apply the same legal transition to additional jobs atomically")
    parser.add_argument("--invalidate", action="store_true", help="return completed work to pending with an explicit reason")
    args = parser.parse_args()
    transitions = {
        "pending": {"assigned", "failed"}, "assigned": {"translated", "failed", "pending"},
        "translated": {"validated", "failed"}, "validated": {"reviewed", "failed"},
        "reviewed": {"approved", "failed"}, "approved": {"merged", "failed"},
        "merged": set(), "failed": {"pending"},
    }
    wanted = {args.job_id, *args.also_job}
    found_ids = set()
    if args.invalidate and (args.status != "pending" or not args.note):
        parser.error("--invalidate requires pending and --note explaining the dependency change")

    path = args.jobs_jsonl.resolve()
    records: list[dict[str, Any]] = []
    found = False
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, raw in enumerate(stream, 1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                parser.error(f"{path}:{line_number}: invalid JSON: {exc}")
            if record.get("job_id") in wanted:
                current_id = record["job_id"]
                if current_id in found_ids:
                    parser.error(f"duplicate job_id: {args.job_id}")
                found_ids.add(current_id)
                previous = record.get("status")
                if not args.invalidate and args.status != previous and args.status not in transitions.get(previous, set()):
                    parser.error(f"illegal transition for {current_id}: {previous} -> {args.status}")
                found = True
                if args.from_status and record.get("status") != args.from_status:
                    parser.error(
                        f"job {args.job_id} is {record.get('status')!r}, expected {args.from_status!r}"
                    )
                record["status"] = args.status
                record["updated_at"] = datetime.now(timezone.utc).isoformat()
                if args.worker is not None:
                    record["worker"] = args.worker
                if args.reviewer is not None:
                    record["reviewer"] = args.reviewer
                if args.note:
                    record.setdefault("status_notes", []).append(args.note)
            records.append(record)
    if found_ids != wanted:
        parser.error(f"job IDs not found: {sorted(wanted - found_ids)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise

    print(json.dumps({"job_ids": sorted(wanted), "status": args.status}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
