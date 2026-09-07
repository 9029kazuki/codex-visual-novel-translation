#!/usr/bin/env python3
"""Record the reviewer's explicit coverage declaration; this is not semantic QA."""
import argparse
import json
import sys
from pathlib import Path
sys.dont_write_bytecode = True
from apply_review_delta import read_jsonl, index_unique, source_digest, canonical_records_digest, validate_delta
from pipeline_common import atomic_text, json_text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_jsonl", type=Path)
    parser.add_argument("draft_jsonl", type=Path)
    parser.add_argument("delta_jsonl", type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--translator", required=True)
    parser.add_argument("--all-entries-reviewed", action="store_true", required=True)
    parser.add_argument("--outcome", choices=("passed", "needs-resolution"), required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.reviewer.strip() or not args.translator.strip() or args.reviewer == args.translator:
        parser.error("reviewer and translator must be distinct nonempty identities")
    try:
        source, draft, delta = (read_jsonl(path.resolve()) for path in (args.source_jsonl, args.draft_jsonl, args.delta_jsonl))
        ids, source_by_id = index_unique(source, "source")
        draft_ids, _ = index_unique(draft, "draft")
        delta_ids, _ = index_unique(delta, "delta")
        if not ids or ids != draft_ids or delta_ids != [x for x in ids if x in set(delta_ids)]:
            raise ValueError("source/draft/delta coverage or order differs")
        for row in delta:
            validate_delta(source_by_id[row["id"]], row)
        report = {"schema_version": 3, "job_id": args.job_id, "reviewer": args.reviewer, "translator": args.translator,
            "reviewed_source_digest": source_digest(source), "reviewed_draft_digest": canonical_records_digest(draft),
            "review_delta_digest": canonical_records_digest(delta), "reviewed_entry_count": len(source),
            "coverage": "all-entries", "delta_count": len(delta), "passed": args.outcome == "passed"}
        if args.report.resolve() in {args.source_jsonl.resolve(), args.draft_jsonl.resolve(), args.delta_jsonl.resolve()}:
            raise ValueError("report must not overwrite an input")
        if args.report.exists():
            raise ValueError("review declaration already exists; write a new review attempt, never overwrite it")
        atomic_text(args.report.resolve(), json_text(report))
        print(json.dumps({"report": str(args.report.resolve()), "declaration_recorded": True, "semantic_qa_performed_by_script": False}))
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
