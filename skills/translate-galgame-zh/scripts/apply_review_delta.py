#!/usr/bin/env python3
"""Validate sparse all-entry review deltas and optionally materialize approved JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ALLOWED_DELTA_FIELDS = {"id", "reviewer_translation", "reason", "severity"}
SEVERITIES = {"minor", "major"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, raw in enumerate(stream, 1):
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            value["__line__"] = line_number
            records.append(value)
    return records


def without_internal(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("__")}


def canonical_records_digest(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        text = json.dumps(
            without_internal(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest.update(text.encode("utf-8"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def source_digest(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(str(record.get("id") or "").encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record.get("source_hash") or "").encode("utf-8"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def index_unique(records: list[dict[str, Any]], label: str) -> tuple[list[str], dict[str, dict[str, Any]]]:
    order: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        entry_id = record.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            raise ValueError(
                f"{label} line {record.get('__line__')} has no non-empty string id"
            )
        if entry_id in by_id:
            raise ValueError(f"{label} contains duplicate id {entry_id!r}")
        order.append(entry_id)
        by_id[entry_id] = record
    return order, by_id


def protected_tokens(source: dict[str, Any]) -> list[str]:
    value = source.get("protected_tokens", [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"source {source.get('id')} has invalid protected_tokens")
    return value


def validate_translation_shape(
    source: dict[str, Any], translation: str, label: str
) -> None:
    if not translation:
        raise ValueError(f"{label} for {source.get('id')} is empty")
    tokens = protected_tokens(source)
    for token, expected in Counter(tokens).items():
        actual = translation.count(token)
        if actual != expected:
            raise ValueError(
                f"{label} for {source.get('id')} changes protected token {token!r}: "
                f"expected {expected}, found {actual}"
            )
    cursor = 0
    for token in tokens:
        position = translation.find(token, cursor)
        if position < 0:
            raise ValueError(
                f"{label} for {source.get('id')} changes protected token order"
            )
        cursor = position + len(token)
    source_text = str(source.get("text") or "")
    if source_text.count("\n") != translation.count("\n"):
        raise ValueError(f"{label} for {source.get('id')} changes newline count")
    if "\ufffd" in translation or "\x00" in translation:
        raise ValueError(f"{label} for {source.get('id')} contains U+FFFD or NUL")


def load_existing_report(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid review report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"review report is not an object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_jsonl", type=Path, help="job-scoped frozen source JSONL")
    parser.add_argument("draft_jsonl", type=Path)
    parser.add_argument("review_delta_jsonl", type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--approved-output", type=Path)
    parser.add_argument(
        "--verify-existing-report",
        action="store_true",
        help="fail instead of replacing the report when its frozen digests differ",
    )
    args = parser.parse_args()

    source_path = args.source_jsonl.resolve()
    draft_path = args.draft_jsonl.resolve()
    delta_path = args.review_delta_jsonl.resolve()
    report_path = args.report.resolve()
    try:
        sources = read_jsonl(source_path)
        drafts = read_jsonl(draft_path)
        deltas = read_jsonl(delta_path)
        source_order, source_by_id = index_unique(sources, "source")
        draft_order, draft_by_id = index_unique(drafts, "draft")
        delta_order, delta_by_id = index_unique(deltas, "review delta")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    if not sources:
        parser.error("job source is empty")
    if draft_order != source_order:
        parser.error("draft ids must exactly cover job source in source order")
    unknown_delta = [entry_id for entry_id in delta_order if entry_id not in source_by_id]
    if unknown_delta:
        parser.error(f"review delta contains unknown ids: {unknown_delta[:10]}")
    expected_delta_order = [entry_id for entry_id in source_order if entry_id in delta_by_id]
    if delta_order != expected_delta_order:
        parser.error("review delta ids must follow source order")

    try:
        for entry_id in source_order:
            source = source_by_id[entry_id]
            draft = draft_by_id[entry_id]
            draft_translation = draft.get("translation")
            if not isinstance(draft_translation, str):
                raise ValueError(f"draft {entry_id} has no string translation")
            expected_hash = source.get("source_hash")
            if (
                expected_hash
                and "source_hash" in draft
                and draft.get("source_hash") != expected_hash
            ):
                raise ValueError(f"draft {entry_id} has a stale source_hash")
            validate_translation_shape(source, draft_translation, "draft translation")

        for entry_id in delta_order:
            delta = delta_by_id[entry_id]
            fields = set(without_internal(delta))
            if fields != ALLOWED_DELTA_FIELDS:
                raise ValueError(
                    f"review delta {entry_id} fields must be exactly "
                    f"{sorted(ALLOWED_DELTA_FIELDS)}, found {sorted(fields)}"
                )
            reviewer_translation = delta.get("reviewer_translation")
            if not isinstance(reviewer_translation, str):
                raise ValueError(f"review delta {entry_id} needs reviewer_translation")
            if not isinstance(delta.get("reason"), str) or not delta["reason"].strip():
                raise ValueError(f"review delta {entry_id} needs a reason")
            if delta.get("severity") not in SEVERITIES:
                raise ValueError(
                    f"review delta {entry_id} severity must be minor or major"
                )
            validate_translation_shape(
                source_by_id[entry_id], reviewer_translation, "reviewer translation"
            )
    except ValueError as exc:
        parser.error(str(exc))

    job_source_digest = source_digest(sources)
    draft_digest = canonical_records_digest(drafts)
    delta_digest = canonical_records_digest(deltas)
    report = {
        "schema_version": 2,
        "job_id": args.job_id,
        "reviewed_source_digest": job_source_digest,
        "reviewed_draft_digest": draft_digest,
        "review_delta_digest": delta_digest,
        "reviewed_entry_count": len(sources),
        "coverage": "all-entries",
        "delta_count": len(deltas),
        "major_count": sum(item.get("severity") == "major" for item in deltas),
        "minor_count": sum(item.get("severity") == "minor" for item in deltas),
        "passed": True,
    }
    try:
        existing_report = load_existing_report(report_path)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.verify_existing_report and existing_report is not None:
        frozen_fields = (
            "job_id",
            "reviewed_source_digest",
            "reviewed_draft_digest",
            "review_delta_digest",
            "reviewed_entry_count",
            "coverage",
            "delta_count",
        )
        mismatches = [
            field
            for field in frozen_fields
            if existing_report.get(field) != report.get(field)
        ]
        if mismatches:
            parser.error(f"existing review report is stale: {mismatches}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    approved_output = args.approved_output.resolve() if args.approved_output else None
    if approved_output is not None:
        approved_output.parent.mkdir(parents=True, exist_ok=True)
        with approved_output.open("w", encoding="utf-8", newline="\n") as stream:
            for entry_id in source_order:
                approved = without_internal(dict(draft_by_id[entry_id]))
                if entry_id in delta_by_id:
                    approved["translation"] = delta_by_id[entry_id][
                        "reviewer_translation"
                    ]
                expected_hash = source_by_id[entry_id].get("source_hash")
                if expected_hash:
                    approved["source_hash"] = expected_hash
                stream.write(json.dumps(approved, ensure_ascii=False) + "\n")

    print(
        json.dumps(
            {
                "job_id": args.job_id,
                "reviewed_entry_count": len(sources),
                "delta_count": len(deltas),
                "report": str(report_path),
                "approved_output": str(approved_output) if approved_output else None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
