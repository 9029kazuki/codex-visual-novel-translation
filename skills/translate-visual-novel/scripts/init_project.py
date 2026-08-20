#!/usr/bin/env python3
"""Initialize a restartable Galgame localization project without overwriting work."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


DIRECTORIES = (
    "source",
    "research",
    "staging/unpacked",
    "staging/roundtrip/input",
    "staging/roundtrip/unpacked",
    "staging/roundtrip/repacked",
    "extracted",
    "bible",
    "planning",
    "planning/decision-snapshots",
    "contexts",
    "contexts/shared-prefix",
    "translations/drafts",
    "translations/approved",
    "reviews",
    "qa",
    "qa/jobs",
    "qa/cache",
    "build",
    "release",
)

LOCALE_TAG = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_text_if_missing(path: Path, text: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def write_json_if_missing(path: Path, value: object) -> bool:
    return write_text_if_missing(
        path, json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--game-name", required=True)
    parser.add_argument("--original-title", default="")
    parser.add_argument("--source-locale", required=True)
    parser.add_argument("--target-locale", required=True)
    parser.add_argument("--instruction-locale", default="en")
    parser.add_argument("--brand", default="")
    parser.add_argument("--version", default="unknown")
    parser.add_argument("--platform", default="Windows")
    parser.add_argument("--source-dir", type=Path)
    args = parser.parse_args()

    for label, value in (
        ("source locale", args.source_locale),
        ("target locale", args.target_locale),
        ("instruction locale", args.instruction_locale),
    ):
        if not LOCALE_TAG.fullmatch(value):
            parser.error(f"invalid {label}: {value!r}")
    if args.source_locale.casefold() == args.target_locale.casefold():
        parser.error("source and target locales must be different")

    if args.source_dir and not args.source_dir.is_dir():
        parser.error(f"source directory does not exist: {args.source_dir}")

    root = args.project_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for relative in DIRECTORIES:
        (root / relative).mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    project = {
        "schema_version": 3,
        "game_name": args.game_name,
        "original_title": args.original_title,
        "titles": ({args.source_locale: args.original_title} if args.original_title else {}),
        "brand": args.brand,
        "version": args.version,
        "platform": args.platform,
        "source_dir": str(args.source_dir.resolve()) if args.source_dir else "",
        "instruction_locale": args.instruction_locale,
        "source_locale": args.source_locale,
        "target_locale": args.target_locale,
        "created_at": now_iso(),
    }
    state = {
        "schema_version": 3,
        "stage": "initialized",
        "updated_at": now_iso(),
        "subagent_mode": "not-checked",
        "bible_version": 0,
        "last_error": None,
        "evidence": [],
        "history": [
            {
                "stage": "initialized",
                "at": now_iso(),
                "note": "project initialized",
                "evidence": ["project.json"],
            }
        ],
    }

    templates: dict[str, str] = {
        "research/sources.jsonl": "",
        "research/unpack-notes.md": "# Extraction and repacking notes\n\n",
        "research/decisions.md": "# Research and translation decisions\n\n",
        "source/signatures.md": "# File signatures and engine identification\n\n",
        "extracted/source.jsonl": "",
        "planning/jobs.jsonl": "",
        "translations/final.jsonl": "",
        "bible/world.md": "# World and narrative rules\n\n",
        "bible/honorifics.md": "# Address, honorific, and register policy\n\n",
        "bible/language-profile.md": (
            "# Language-pair profile\n\n"
            f"- Source locale: `{args.source_locale}`\n"
            f"- Target locale: `{args.target_locale}`\n\n"
            "Define punctuation, quotation, spacing, casing, transliteration, "
            "names, register, address forms, line breaking, and source-specific "
            "translation risks before freezing the Bible.\n"
        ),
        "bible/glossary.tsv": (
            "source\ttarget\tsource_locale\ttarget_locale\treading\tcategory\tstatus\t"
            "scope\tmatch_mode\tcase_sensitive\tsource_url\tnotes\n"
        ),
        "bible/calibration.jsonl": "",
    }
    json_templates: dict[str, object] = {
        "project.json": project,
        "run-state.json": state,
        "planning/translation-decisions.json": {
            "schema_version": 2,
            "source_locale": args.source_locale,
            "target_locale": args.target_locale,
            "accepted": [],
            "knowledge_corrections": [],
            "pending": [],
        },
        "extracted/script-map.json": {"schema_version": 1, "nodes": [], "edges": []},
        "extracted/control-token-report.json": {"schema_version": 1, "engines": []},
        "bible/characters.json": {
            "schema_version": 2,
            "source_locale": args.source_locale,
            "target_locale": args.target_locale,
            "characters": [],
        },
        "bible/voice.json": {
            "schema_version": 2,
            "target_locale": args.target_locale,
            "narrator": {},
            "characters": {},
        },
        "bible/route-knowledge.json": {"schema_version": 1, "global": {}, "routes": {}},
        "bible/version.json": {
            "version": 0,
            "frozen": False,
            "language_profile_version": 0,
            "updated_at": now_iso(),
            "changes": [],
        },
        "qa/roundtrip-report.json": {"schema_version": 1, "passed": False, "evidence": []},
        "qa/global.json": {"schema_version": 1, "errors": None, "warnings": None},
        "qa/repack-report.json": {"schema_version": 1, "passed": False, "evidence": []},
        "qa/playtest-report.json": {"schema_version": 1, "passed": False, "coverage": []},
        "qa/release-report.json": {"schema_version": 1, "passed": False, "evidence": []},
    }

    for relative, text in templates.items():
        if write_text_if_missing(root / relative, text):
            created.append(relative)
    for relative, value in json_templates.items():
        if write_json_if_missing(root / relative, value):
            created.append(relative)

    print(
        json.dumps(
            {"project_root": str(root), "created": created, "preserved_existing": True},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
