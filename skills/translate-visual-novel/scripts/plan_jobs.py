#!/usr/bin/env python3
"""Propose scene translation jobs from extracted source JSONL."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, raw in enumerate(stream, 1):
            if not raw.strip():
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(item, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            entry_id = item.get("id")
            if not isinstance(entry_id, str) or not entry_id:
                raise ValueError(f"{path}:{line_number}: missing string id")
            if entry_id in seen:
                raise ValueError(f"{path}:{line_number}: duplicate id {entry_id!r}")
            if not isinstance(item.get("text"), str):
                raise ValueError(f"{path}:{line_number}: missing string text")
            source_hash = item.get("source_hash")
            if not isinstance(source_hash, str) or not re.fullmatch(
                r"sha256:[0-9a-fA-F]{64}", source_hash
            ):
                raise ValueError(
                    f"{path}:{line_number}: source_hash must be sha256 plus 64 hex digits"
                )
            seen.add(entry_id)
            records.append(item)
    return records


def scene_key(record: dict[str, Any]) -> tuple[str, str, str]:
    route = str(record.get("route") or "unassigned")
    scene = str(record.get("scene_id") or record.get("file") or "unassigned")
    merge_group = str(record.get("merge_group") or "")
    return route, scene, merge_group


def consecutive_groups(
    records: Iterable[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_key: tuple[str, str, str] | None = None
    for record in records:
        key = scene_key(record)
        # An explicit merge_group may join adjacent scene labels on the same route.
        normalized = (key[0], f"merge:{key[2]}", key[2]) if key[2] else key
        if current and normalized != current_key:
            groups.append(current)
            current = []
        current_key = normalized
        current.append(record)
    if current:
        groups.append(current)
    return groups


def split_group(
    group: list[dict[str, Any]], max_chars: int
) -> list[tuple[list[dict[str, Any]], bool]]:
    if max_chars <= 0:
        return [(group, False)]
    result: list[tuple[list[dict[str, Any]], bool]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    forced_split = False
    for record in group:
        length = len(record["text"])
        if current and current_chars + length > max_chars:
            natural = bool(record.get("boundary_before"))
            result.append((current, forced_split or not natural))
            current = []
            current_chars = 0
            forced_split = not natural
        current.append(record)
        current_chars += length
    if current:
        result.append((current, forced_split or current_chars > max_chars))
    return result


def slug(value: str) -> str:
    value = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-._")
    return (value or "scene")[:60]


def source_digest(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(record["id"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record.get("source_hash") or record["text"]).encode("utf-8"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def decision_snapshot_digest(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    elif suffix == ".jsonl":
        lines: list[str] = []
        with path.open("r", encoding="utf-8-sig") as stream:
            for line_number, raw in enumerate(stream, 1):
                if not raw.strip():
                    continue
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
                lines.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
        text = "\n".join(lines) + ("\n" if lines else "")
    else:
        text = path.read_text(encoding="utf-8-sig")
        text = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_jsonl", type=Path)
    parser.add_argument("output_jsonl", type=Path)
    parser.add_argument(
        "--max-source-chars",
        type=int,
        default=0,
        help="optional planning split; 0 keeps complete scene groups intact",
    )
    parser.add_argument("--min-source-chars", type=int, default=1500)
    parser.add_argument("--bible-version", type=int, default=0)
    parser.add_argument(
        "--decision-snapshot",
        type=Path,
        help="frozen JSON/JSONL/Markdown decision snapshot for this cohort",
    )
    args = parser.parse_args()

    records = read_jsonl(args.source_jsonl.resolve())
    decision_path = args.decision_snapshot.resolve() if args.decision_snapshot else None
    if decision_path is not None and not decision_path.is_file():
        parser.error(f"decision snapshot does not exist: {decision_path}")
    try:
        decision_digest = (
            decision_snapshot_digest(decision_path) if decision_path is not None else None
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    jobs: list[dict[str, Any]] = []
    for group in consecutive_groups(records):
        pieces = split_group(group, args.max_source_chars)
        part_count = len(pieces)
        for records_in_job, forced_split in pieces:
            first = records_in_job[0]
            scene_ids = list(
                dict.fromkeys(
                    str(item.get("scene_id") or item.get("file") or "unassigned")
                    for item in records_in_job
                )
            )
            route = str(first.get("route") or "unassigned")
            char_count = sum(len(item["text"]) for item in records_in_job)
            index = len(jobs) + 1
            part_suffix = f"-p{len([j for j in jobs if j['scene_ids'] == scene_ids]) + 1}" if part_count > 1 else ""
            job_id = f"job-{index:05d}-{slug(scene_ids[0])}{part_suffix}"
            missing_scene = any(not item.get("scene_id") for item in records_in_job)
            speakers = sorted(
                {
                    str(item["speaker"])
                    for item in records_in_job
                    if item.get("speaker") not in (None, "")
                }
            )
            jobs.append(
                {
                    "job_id": job_id,
                    "status": "pending",
                    "route": route,
                    "scene_ids": scene_ids,
                    "source_files": list(
                        dict.fromkeys(str(item.get("file") or "") for item in records_in_job)
                    ),
                    "entry_ids": [item["id"] for item in records_in_job],
                    "speakers": speakers,
                    "source_char_count": char_count,
                    "estimated_source_tokens": math.ceil(char_count * 1.15),
                    "source_digest": source_digest(records_in_job),
                    "bible_version": args.bible_version,
                    "decision_snapshot": str(decision_path) if decision_path else None,
                    "decision_snapshot_digest": decision_digest,
                    "plan_approved": False,
                    "predecessors": [],
                    "adjacent_entry_ids": [],
                    "time": "",
                    "location": "",
                    "prior_summary": "",
                    "context_notes": "",
                    "needs_boundary_review": bool(
                        forced_split or missing_scene or char_count < args.min_source_chars
                    ),
                    "boundary_review_reasons": [
                        reason
                        for condition, reason in (
                            (forced_split, "size split was not at an explicit boundary"),
                            (missing_scene, "one or more records lack scene_id"),
                            (char_count < args.min_source_chars, "scene is small; consider merging"),
                        )
                        if condition
                    ],
                    "worker": None,
                    "reviewer": None,
                    "updated_at": None,
                }
            )

    output = args.output_jsonl.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for job in jobs:
            stream.write(json.dumps(job, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "output": str(output),
                "source_records": len(records),
                "jobs": len(jobs),
                "jobs_needing_review": sum(job["needs_boundary_review"] for job in jobs),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
