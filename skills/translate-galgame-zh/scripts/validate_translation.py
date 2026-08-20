#!/usr/bin/env python3
"""Validate one or all translated JSONL files against frozen source records."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


JAPANESE_KANA = re.compile(r"[\u3041-\u3096\u30a1-\u30fa]")
SEMANTIC_TEXT = re.compile(r"[\w\u3400-\u9fff]", re.UNICODE)
CONFIDENCE_VALUES = {"high", "medium", "low"}


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


def read_glossary(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream, delimiter="\t")]


def add_issue(
    issues: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    entry_id: str | None = None,
) -> None:
    issue: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if entry_id is not None:
        issue["id"] = entry_id
    issues.append(issue)


def scope_applies(row: dict[str, str], source: dict[str, Any]) -> bool:
    scope = (row.get("scope") or "").strip()
    if not scope or scope == "global":
        return True
    candidates = {
        str(source.get("route") or ""),
        str(source.get("scene_id") or ""),
        str(source.get("speaker") or ""),
    }
    return scope in candidates


def remove_protected_tokens(text: str, tokens: list[str]) -> str:
    result = text
    for token in sorted(set(tokens), key=len, reverse=True):
        if token:
            result = result.replace(token, "")
    return result


def glossary_row_is_shadowed(
    row: dict[str, str],
    applicable_rows: list[dict[str, str]],
    source_text: str,
    translation: str,
) -> bool:
    source_term = (row.get("source") or "").strip()
    if not source_term:
        return False
    for other in applicable_rows:
        longer_source = (other.get("source") or "").strip()
        longer_target = (other.get("target") or "").strip()
        if (
            len(longer_source) > len(source_term)
            and source_term in longer_source
            and longer_source in source_text
            and longer_target
            and longer_target in translation
        ):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_jsonl", type=Path)
    parser.add_argument("translation_jsonl", type=Path)
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--allow-subset", action="store_true")
    args = parser.parse_args()

    source_path = args.source_jsonl.resolve()
    translation_path = args.translation_jsonl.resolve()
    report_path = (
        args.report.resolve()
        if args.report
        else translation_path.with_suffix(translation_path.suffix + ".qa.json")
    )
    issues: list[dict[str, Any]] = []
    try:
        sources = read_jsonl(source_path)
        targets = read_jsonl(translation_path)
    except (OSError, ValueError) as exc:
        add_issue(issues, "error", "input-read", str(exc))
        sources, targets = [], []

    source_by_id: dict[str, dict[str, Any]] = {}
    for item in sources:
        entry_id = item.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            add_issue(
                issues,
                "error",
                "source-id",
                f"source line {item.get('__line__')} has no string id",
            )
            continue
        if entry_id in source_by_id:
            add_issue(issues, "error", "duplicate-source-id", "duplicate source id", entry_id)
        source_by_id[entry_id] = item

    target_by_id: dict[str, dict[str, Any]] = {}
    target_order: list[str] = []
    for item in targets:
        entry_id = item.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            add_issue(
                issues,
                "error",
                "target-id",
                f"translation line {item.get('__line__')} has no string id",
            )
            continue
        if entry_id in target_by_id:
            add_issue(issues, "error", "duplicate-target-id", "duplicate translation id", entry_id)
        target_by_id[entry_id] = item
        target_order.append(entry_id)

    source_ids = list(source_by_id)
    target_ids = list(target_by_id)
    missing = [entry_id for entry_id in source_ids if entry_id not in target_by_id]
    extra = [entry_id for entry_id in target_ids if entry_id not in source_by_id]
    if missing and not args.allow_subset:
        add_issue(
            issues,
            "error",
            "missing-ids",
            f"missing {len(missing)} ids; first: {missing[:10]}",
        )
    if extra:
        add_issue(
            issues,
            "error",
            "extra-ids",
            f"unknown {len(extra)} ids; first: {extra[:10]}",
        )
    expected_order = [entry_id for entry_id in source_ids if entry_id in target_by_id]
    actual_order = [entry_id for entry_id in target_order if entry_id in source_by_id]
    if actual_order != expected_order:
        add_issue(issues, "error", "id-order", "translation ids are not in source order")

    glossary = read_glossary(args.glossary.resolve() if args.glossary else None)
    same_source_translations: dict[str, set[str]] = defaultdict(set)
    for entry_id in expected_order:
        source = source_by_id[entry_id]
        target = target_by_id[entry_id]
        translation = target.get("translation")
        if not isinstance(translation, str) or not translation:
            add_issue(issues, "error", "empty-translation", "translation is empty", entry_id)
            continue
        source_text = str(source.get("text") or "")
        same_source_translations[source_text].add(translation)

        expected_hash = source.get("source_hash")
        if (
            expected_hash
            and "source_hash" in target
            and target.get("source_hash") != expected_hash
        ):
            add_issue(
                issues,
                "error",
                "source-hash",
                "provided source_hash does not match",
                entry_id,
            )

        tokens = source.get("protected_tokens", [])
        if tokens is None:
            tokens = []
        if not isinstance(tokens, list) or any(not isinstance(token, str) for token in tokens):
            add_issue(
                issues,
                "error",
                "protected-token-schema",
                "source protected_tokens must be a string array",
                entry_id,
            )
            tokens = []
        expected_counts = Counter(tokens)
        for token, expected_count in expected_counts.items():
            actual_count = translation.count(token)
            if actual_count != expected_count:
                add_issue(
                    issues,
                    "error",
                    "protected-token-count",
                    f"token {token!r}: expected {expected_count}, found {actual_count}",
                    entry_id,
                )
        cursor = 0
        for token in tokens:
            position = translation.find(token, cursor)
            if position < 0:
                break
            cursor = position + len(token)
        else:
            position = 0
        if tokens and position < 0:
            add_issue(
                issues,
                "error",
                "protected-token-order",
                "protected tokens are missing or out of order",
                entry_id,
            )

        if source_text.count("\n") != translation.count("\n"):
            add_issue(
                issues,
                "error",
                "newline-count",
                f"expected {source_text.count(chr(10))} newlines, found {translation.count(chr(10))}",
                entry_id,
            )
        if "\ufffd" in translation or "\x00" in translation:
            add_issue(issues, "error", "invalid-character", "contains U+FFFD or NUL", entry_id)
        source_visible = remove_protected_tokens(source_text, tokens).strip()
        translation_visible = remove_protected_tokens(translation, tokens).strip()
        if (
            translation == source_text
            and source_text
            and SEMANTIC_TEXT.search(source_visible)
        ):
            add_issue(issues, "warning", "source-unchanged", "translation equals source", entry_id)
        kana = JAPANESE_KANA.findall(translation_visible)
        if kana:
            add_issue(
                issues,
                "warning",
                "residual-kana",
                f"contains Japanese kana, sample: {''.join(kana[:12])}",
                entry_id,
            )
        if source_visible:
            ratio = len(translation_visible) / max(1, len(source_visible))
            if ratio < 0.12 or ratio > 4.0:
                add_issue(
                    issues,
                    "warning",
                    "length-ratio",
                    f"unusual target/source character ratio: {ratio:.2f}",
                    entry_id,
                )
        confidence = target.get("confidence")
        if confidence not in CONFIDENCE_VALUES:
            add_issue(
                issues,
                "warning",
                "confidence",
                "confidence should be high, medium, or low",
                entry_id,
            )
        for field in ("issues", "term_proposals"):
            if field in target and not isinstance(target[field], list):
                add_issue(
                    issues,
                    "error",
                    f"{field}-schema",
                    f"{field} must be an array",
                    entry_id,
                )

        applicable_glossary = [row for row in glossary if scope_applies(row, source)]
        for row in applicable_glossary:
            term_source = (row.get("source") or "").strip()
            term_target = (row.get("target") or "").strip()
            status = (row.get("status") or "").strip().lower()
            if status == "forbidden" and term_target and term_target in translation:
                add_issue(
                    issues,
                    "error",
                    "forbidden-term",
                    f"forbidden target term appears: {term_target}",
                    entry_id,
                )
            if (
                term_source
                and term_source in source_text
                and term_target
                and not glossary_row_is_shadowed(
                    row, applicable_glossary, source_text, translation
                )
            ):
                if status == "locked" and term_target not in translation:
                    add_issue(
                        issues,
                        "error",
                        "locked-term",
                        f"locked translation missing: {term_source} -> {term_target}",
                        entry_id,
                    )
                elif status == "preferred" and term_target not in translation:
                    add_issue(
                        issues,
                        "warning",
                        "preferred-term",
                        f"preferred translation missing: {term_source} -> {term_target}",
                        entry_id,
                    )

    for source_text, translations in same_source_translations.items():
        if source_text and len(translations) > 1 and SEMANTIC_TEXT.search(source_text):
            add_issue(
                issues,
                "warning",
                "repeat-inconsistency",
                f"same source has {len(translations)} different translations: {source_text[:40]!r}",
            )

    errors = sum(issue["severity"] == "error" for issue in issues)
    warnings = sum(issue["severity"] == "warning" for issue in issues)
    report = {
        "schema_version": 2,
        "source": str(source_path),
        "translation": str(translation_path),
        "source_records": len(sources),
        "translation_records": len(targets),
        "source_hash_policy": "reconstructed; provided values must match",
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {"report": str(report_path), "errors": errors, "warnings": warnings},
            ensure_ascii=False,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
