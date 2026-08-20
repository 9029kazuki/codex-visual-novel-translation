#!/usr/bin/env python3
"""Initialize a restartable Galgame localization project without overwriting work."""

from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--japanese-title", default="")
    parser.add_argument("--brand", default="")
    parser.add_argument("--version", default="unknown")
    parser.add_argument("--platform", default="Windows")
    parser.add_argument("--source-dir", type=Path)
    args = parser.parse_args()

    if args.source_dir and not args.source_dir.is_dir():
        parser.error(f"source directory does not exist: {args.source_dir}")

    root = args.project_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for relative in DIRECTORIES:
        (root / relative).mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    project = {
        "schema_version": 2,
        "game_name": args.game_name,
        "japanese_title": args.japanese_title,
        "brand": args.brand,
        "version": args.version,
        "platform": args.platform,
        "source_dir": str(args.source_dir.resolve()) if args.source_dir else "",
        "target_language": "zh-CN",
        "created_at": now_iso(),
    }
    state = {
        "schema_version": 2,
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
        "research/unpack-notes.md": "# 解包与封包记录\n\n",
        "research/decisions.md": "# 研究与本地化裁决\n\n",
        "source/signatures.md": "# 文件签名与引擎判断\n\n",
        "extracted/source.jsonl": "",
        "planning/jobs.jsonl": "",
        "translations/final.jsonl": "",
        "bible/world.md": "# 世界观与剧情规则\n\n",
        "bible/honorifics.md": "# 称谓与敬称策略\n\n",
        "bible/glossary.tsv": (
            "source\ttarget\treading\tcategory\tstatus\tscope\tsource_url\tnotes\n"
        ),
        "bible/calibration.jsonl": "",
    }
    json_templates: dict[str, object] = {
        "project.json": project,
        "run-state.json": state,
        "planning/translation-decisions.json": {
            "schema_version": 1,
            "accepted": [],
            "knowledge_corrections": [],
            "pending": [],
        },
        "extracted/script-map.json": {"schema_version": 1, "nodes": [], "edges": []},
        "extracted/control-token-report.json": {"schema_version": 1, "engines": []},
        "bible/characters.json": {"schema_version": 1, "characters": []},
        "bible/voice.json": {"schema_version": 1, "narrator": {}, "characters": {}},
        "bible/route-knowledge.json": {"schema_version": 1, "global": {}, "routes": {}},
        "bible/version.json": {
            "version": 0,
            "frozen": False,
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
