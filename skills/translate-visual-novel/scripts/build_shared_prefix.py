#!/usr/bin/env python3
"""Build a deterministic shared translation prefix for a clean subagent seed."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
from audit_project import validate_project


SCHEMA_VERSION = 1
SKILL_REVISION = 1


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


def read_text(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"required file does not exist: {path}")
    return normalize_text(path.read_text(encoding="utf-8-sig"))


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ValueError(f"cannot read JSON file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def canonical_json_file(path: Path) -> str:
    return canonical_json(read_json(path))


def canonical_jsonl_file(path: Path) -> str:
    rows: list[str] = []
    if not path.is_file():
        return ""
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, raw in enumerate(stream, 1):
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            rows.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return "\n".join(rows) + ("\n" if rows else "")


def canonical_tsv_file(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"required TSV file does not exist: {path}")
    rows: list[list[str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter="\t")
        rows.extend([[str(cell) for cell in row] for row in reader])
    return "\n".join("\t".join(row) for row in rows).rstrip("\n") + "\n"


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def project_relative(project: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        return path.name


def fenced(language: str, value: str) -> str:
    value = value.rstrip("\n")
    return f"```{language}\n{value}\n```\n"


def choose_decisions(project: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        path = explicit.resolve()
        if not path.is_file():
            raise ValueError(f"decision snapshot does not exist: {path}")
        return path
    candidates = (
        project / "planning/translation-decisions.json",
        project / "research/decisions.md",
    )
    for path in candidates:
        if path.is_file() and path.stat().st_size:
            return path
    raise ValueError(
        "no decision snapshot found; provide --decisions or create "
        "planning/translation-decisions.json"
    )


def render_decisions(path: Path) -> tuple[str, str]:
    suffix = path.suffix.casefold()
    if suffix == ".json":
        value = canonical_json_file(path)
        return fenced("json", value), sha256_text(value)
    if suffix == ".jsonl":
        value = canonical_jsonl_file(path)
        return fenced("jsonl", value), sha256_text(value)
    value = read_text(path)
    return value, sha256_text(value)


def write_if_same_or_missing(path: Path, text: str) -> None:
    if path.exists():
        existing = path.read_text(encoding="utf-8-sig")
        if normalize_text(existing) != normalize_text(text):
            raise ValueError(f"refusing to overwrite different immutable prefix file: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalize_text(text), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--decisions", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--expected-prefix-tokens",
        type=int,
        help="optional observed/externally counted token boundary for cache probes",
    )
    args = parser.parse_args()

    project = args.project_root.resolve()
    gate_issues = validate_project(project, "bible-frozen")
    if gate_issues:
        parser.error("project bible is not ready: " + " | ".join(gate_issues))

    bible_state = read_json(project / "bible/version.json")
    bible_version = bible_state.get("version") if isinstance(bible_state, dict) else None
    if not isinstance(bible_version, int) or bible_version < 1:
        parser.error("bible/version.json must contain a frozen integer version >= 1")
    project_data = read_json(project / "project.json")
    if not isinstance(project_data, dict):
        parser.error("project.json must contain an object")
    source_locale = project_data.get("source_locale")
    target_locale = project_data.get("target_locale")
    if not isinstance(source_locale, str) or not isinstance(target_locale, str):
        parser.error("project.json must contain source_locale and target_locale")

    skill_root = Path(__file__).resolve().parent.parent
    contract_path = (
        args.contract.resolve()
        if args.contract
        else skill_root / "references/translation-contract.md"
    )
    try:
        decisions_path = choose_decisions(project, args.decisions)
        decisions_rendered, decisions_digest = render_decisions(decisions_path)
        contract = read_text(contract_path)
        language_profile = read_text(project / "bible/language-profile.md")
        world = read_text(project / "bible/world.md")
        characters = canonical_json_file(project / "bible/characters.json")
        voice = canonical_json_file(project / "bible/voice.json")
        honorifics = read_text(project / "bible/honorifics.md")
        glossary = canonical_tsv_file(project / "bible/glossary.tsv")
        route_knowledge = canonical_json_file(project / "bible/route-knowledge.json")
        calibration = canonical_jsonl_file(project / "bible/calibration.jsonl")
    except ValueError as exc:
        parser.error(str(exc))

    sections: list[tuple[str, str]] = [
        (
            "00-translation-contract.md",
            "# Shared translation contract\n\n"
            + contract
            + "\n# Frozen language-pair profile\n\n"
            + language_profile,
        ),
        (
            "10-canon-and-voice.md",
            "# Canon, characters, and voice\n\n"
            "## World and narrative rules\n\n"
            + world
            + "\n## Complete character records\n\n"
            + fenced("json", characters)
            + "\n## Complete voice records\n\n"
            + fenced("json", voice),
        ),
        (
            "20-terminology-and-knowledge.md",
            "# Terminology, address, knowledge gates, and examples\n\n"
            "## Address and register policy\n\n"
            + honorifics
            + "\n## Complete glossary\n\n"
            + fenced("tsv", glossary)
            + "\n## Route knowledge gates\n\n"
            + fenced("json", route_knowledge)
            + "\n## Approved translation examples\n\n"
            + (fenced("jsonl", calibration) if calibration else "None.\n"),
        ),
        (
            "30-decisions.md",
            "# Frozen decisions for the current translation cohort\n\n"
            + decisions_rendered,
        ),
    ]
    sections = [(name, normalize_text(text)) for name, text in sections]
    shared_text = normalize_text("\n".join(text.rstrip("\n") for _, text in sections))
    prefix_digest = sha256_text(shared_text)
    prefix_id = prefix_digest.removeprefix("sha256:")[:20]
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else project / "contexts/shared-prefix" / prefix_id
    )

    section_manifest: list[dict[str, Any]] = []
    for index, (name, text) in enumerate(sections):
        relative = f"sections/{name}"
        section_manifest.append(
            {
                "index": index,
                "file": relative,
                "sha256": sha256_text(text),
                "chars": len(text),
                "bytes": len(text.encode("utf-8")),
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "skill_name": "translate-visual-novel",
        "skill_revision": SKILL_REVISION,
        "prefix_id": prefix_id,
        "prefix_sha256": prefix_digest,
        "prefix_chars": len(shared_text),
        "prefix_bytes": len(shared_text.encode("utf-8")),
        "expected_cached_prefix_tokens": args.expected_prefix_tokens,
        "source_locale": source_locale,
        "target_locale": target_locale,
        "bible_version": bible_version,
        "decision_snapshot": {
            "source": project_relative(project, decisions_path),
            "sha256": decisions_digest,
        },
        "seed_read_order": [item["file"] for item in section_manifest],
        "sections": section_manifest,
    }
    manifest_text = canonical_json(manifest)

    try:
        for name, text in sections:
            write_if_same_or_missing(output_dir / "sections" / name, text)
        write_if_same_or_missing(output_dir / "shared-prefix.md", shared_text)
        write_if_same_or_missing(
            output_dir / "shared-prefix-manifest.json", manifest_text
        )
    except ValueError as exc:
        parser.error(str(exc))

    current = {
        "schema_version": SCHEMA_VERSION,
        "prefix_id": prefix_id,
        "prefix_sha256": prefix_digest,
        "manifest": project_relative(
            project, output_dir / "shared-prefix-manifest.json"
        ),
    }
    current_path = project / "contexts/shared-prefix/current.json"
    current_path.parent.mkdir(parents=True, exist_ok=True)
    current_path.write_text(
        canonical_json(current), encoding="utf-8", newline="\n"
    )

    print(
        json.dumps(
            {
                "prefix_id": prefix_id,
                "prefix_sha256": prefix_digest,
                "manifest": str(output_dir / "shared-prefix-manifest.json"),
                "sections": len(sections),
                "prefix_chars": len(shared_text),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
