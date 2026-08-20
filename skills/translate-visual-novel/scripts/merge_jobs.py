#!/usr/bin/env python3
"""Merge approved job JSONL files in frozen source order."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
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
            records.append(item)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_jsonl", type=Path)
    parser.add_argument("approved_dir", type=Path)
    parser.add_argument("output_jsonl", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()

    source_path = args.source_jsonl.resolve()
    approved_dir = args.approved_dir.resolve()
    if not approved_dir.is_dir():
        parser.error(f"approved directory does not exist: {approved_dir}")
    sources = read_jsonl(source_path)
    source_ids: list[str] = []
    source_by_id: dict[str, dict[str, Any]] = {}
    for item in sources:
        entry_id = item.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            parser.error("source contains an entry without string id")
        if entry_id in source_by_id:
            parser.error(f"duplicate source id: {entry_id}")
        source_ids.append(entry_id)
        source_by_id[entry_id] = item

    translations: dict[str, dict[str, Any]] = {}
    origins: dict[str, Path] = {}
    files = sorted(approved_dir.rglob("*.jsonl"), key=lambda path: path.as_posix().casefold())
    for path in files:
        for item in read_jsonl(path):
            entry_id = item.get("id")
            if not isinstance(entry_id, str) or not entry_id:
                parser.error(f"{path}: translation entry lacks string id")
            if entry_id not in source_by_id:
                parser.error(f"{path}: unknown id {entry_id}")
            if entry_id in translations:
                parser.error(
                    f"id {entry_id} appears in both {origins[entry_id]} and {path}; task boundaries overlap"
                )
            if not isinstance(item.get("translation"), str) or not item["translation"]:
                parser.error(f"{path}: empty translation for {entry_id}")
            expected_hash = source_by_id[entry_id].get("source_hash")
            if (
                expected_hash
                and "source_hash" in item
                and item.get("source_hash") != expected_hash
            ):
                parser.error(f"{path}: source_hash mismatch for {entry_id}")
            merged_item = dict(item)
            if expected_hash:
                merged_item["source_hash"] = expected_hash
            translations[entry_id] = merged_item
            origins[entry_id] = path

    missing = [entry_id for entry_id in source_ids if entry_id not in translations]
    if missing and not args.allow_incomplete:
        parser.error(f"missing {len(missing)} translations; first: {missing[:10]}")

    output = args.output_jsonl.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for entry_id in source_ids:
            if entry_id in translations:
                stream.write(json.dumps(translations[entry_id], ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "output": str(output),
                "approved_files": len(files),
                "merged_records": len(translations),
                "missing_records": len(missing),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
