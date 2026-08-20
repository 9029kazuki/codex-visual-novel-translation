#!/usr/bin/env python3
"""Build a deterministic job bundle with a slim model view and chunk plan."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
from audit_project import validate_project


SKILL_REVISION = 1
BUNDLE_SCHEMA = 2
MODEL_FIELDS = ("id", "kind", "speaker", "text", "protected_tokens")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
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


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def jsonl_text(records: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records)


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_digest(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(str(record.get("id") or "").encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record.get("source_hash") or "").encode("utf-8"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def project_relative(project: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def model_record(record: dict[str, Any]) -> dict[str, Any]:
    tokens = record.get("protected_tokens")
    if not isinstance(tokens, list):
        tokens = []
    return {
        "id": str(record.get("id") or ""),
        "kind": str(record.get("kind") or record.get("type") or ""),
        "speaker": str(record.get("speaker") or ""),
        "text": str(record.get("text") or ""),
        "protected_tokens": [str(token) for token in tokens],
    }


def machine_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "source_hash": record.get("source_hash"),
        "file": record.get("file"),
        "order": record.get("order"),
        "route": record.get("route"),
        "scene_id": record.get("scene_id"),
    }


def character_names(character: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ("id", "name", "jp_name", "source_name", "zh_name", "target_name"):
        value = character.get(key)
        if isinstance(value, str) and value:
            values.add(value)
    aliases = character.get("aliases", [])
    if isinstance(aliases, list):
        values.update(str(value) for value in aliases if value)
    return values


def select_characters(payload: Any, speakers: set[str], scene_text: str) -> list[Any]:
    items = payload.get("characters", []) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    selected: list[Any] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        names = character_names(item)
        if names & speakers or any(name and name in scene_text for name in names):
            selected.append(item)
    return selected


def select_voice(payload: Any, speakers: set[str], characters: list[Any]) -> Any:
    if not isinstance(payload, dict):
        return payload
    result: dict[str, Any] = {}
    if "narrator" in payload:
        result["narrator"] = payload["narrator"]
    voices = payload.get("characters", {})
    if not isinstance(voices, dict):
        return result
    names = set(speakers)
    for character in characters:
        if isinstance(character, dict):
            names.update(character_names(character))
    result["characters"] = {
        key: value for key, value in voices.items() if str(key) in names
    }
    return result


def read_glossary(path: Path, scene_text: str, speakers: set[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    selected: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        for row in reader:
            source = (row.get("source") or "").strip()
            target = (row.get("target") or "").strip()
            if source and (source in scene_text or source in speakers or target in speakers):
                selected.append(dict(row))
    return selected


def select_route_knowledge(payload: Any, route: str) -> Any:
    if not isinstance(payload, dict):
        return payload
    routes = payload.get("routes", {})
    return {
        "global": payload.get("global", {}),
        "route": routes.get(route, {}) if isinstance(routes, dict) else {},
    }


def select_calibration(
    path: Path, speakers: set[str], glossary: list[dict[str, str]], limit: int = 50
) -> list[dict[str, Any]]:
    terms = {row.get("source", "") for row in glossary if row.get("source")}
    selected: list[dict[str, Any]] = []
    for item in read_jsonl(path):
        source = str(item.get("source") or item.get("text") or "")
        speaker = str(item.get("speaker") or "")
        if speaker in speakers or any(term in source for term in terms):
            selected.append(item)
            if len(selected) >= limit:
                break
    return selected


def json_block(value: Any) -> str:
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```"


def resolve_shared_manifest(
    project: Path, explicit: Path | None, standalone: bool
) -> tuple[Path | None, dict[str, Any] | None]:
    if standalone:
        return None, None
    manifest_path: Path | None = explicit.resolve() if explicit else None
    if manifest_path is None:
        pointer_path = project / "contexts/shared-prefix/current.json"
        pointer = read_json(pointer_path, {})
        if isinstance(pointer, dict) and pointer.get("manifest"):
            candidate = Path(str(pointer["manifest"]))
            manifest_path = candidate if candidate.is_absolute() else project / candidate
    if manifest_path is None:
        return None, None
    if not manifest_path.is_file():
        raise ValueError(f"shared prefix manifest does not exist: {manifest_path}")
    manifest = read_json(manifest_path, None)
    if not isinstance(manifest, dict):
        raise ValueError(f"shared prefix manifest is invalid: {manifest_path}")
    prefix_path = manifest_path.parent / "shared-prefix.md"
    if not prefix_path.is_file():
        raise ValueError(f"shared prefix text is missing: {prefix_path}")
    actual_prefix_digest = sha256_text(prefix_path.read_text(encoding="utf-8-sig"))
    if actual_prefix_digest != manifest.get("prefix_sha256"):
        raise ValueError("shared prefix digest does not match its manifest")
    for section in manifest.get("sections", []):
        if not isinstance(section, dict) or not section.get("file"):
            raise ValueError("shared prefix manifest contains an invalid section")
        section_path = manifest_path.parent / str(section["file"])
        if not section_path.is_file():
            raise ValueError(f"shared prefix section is missing: {section_path}")
        actual = sha256_text(section_path.read_text(encoding="utf-8-sig"))
        if actual != section.get("sha256"):
            raise ValueError(f"shared prefix section digest mismatch: {section_path}")
    return manifest_path.resolve(), manifest


def natural_units(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    units: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_scene: str | None = None
    for record in records:
        scene = str(record.get("scene_id") or record.get("file") or "")
        boundary = bool(record.get("boundary_before"))
        if current and (boundary or scene != current_scene):
            units.append(current)
            current = []
        current_scene = scene
        current.append(record)
    if current:
        units.append(current)
    return units


def split_oversized_unit(
    unit: list[dict[str, Any]], target_chars: int
) -> list[tuple[list[dict[str, Any]], bool]]:
    if target_chars <= 0:
        return [(unit, False)]
    result: list[tuple[list[dict[str, Any]], bool]] = []
    current: list[dict[str, Any]] = []
    chars = 0
    for record in unit:
        length = len(str(record.get("text") or ""))
        if current and chars + length > target_chars:
            result.append((current, True))
            current = []
            chars = 0
        current.append(record)
        chars += length
    if current:
        result.append((current, len(result) > 0 or chars > target_chars))
    return result


def build_primary_chunks(
    records: list[dict[str, Any]], target_chars: int
) -> list[tuple[list[dict[str, Any]], bool]]:
    if target_chars <= 0:
        return [(records, False)]
    pieces: list[tuple[list[dict[str, Any]], bool]] = []
    for unit in natural_units(records):
        if sum(len(str(item.get("text") or "")) for item in unit) > target_chars:
            pieces.extend(split_oversized_unit(unit, target_chars))
        else:
            pieces.append((unit, False))

    chunks: list[tuple[list[dict[str, Any]], bool]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    current_forced = False
    for piece, forced in pieces:
        piece_chars = sum(len(str(item.get("text") or "")) for item in piece)
        if current and current_chars + piece_chars > target_chars:
            chunks.append((current, current_forced))
            current = []
            current_chars = 0
            current_forced = False
        current.extend(piece)
        current_chars += piece_chars
        current_forced = current_forced or forced
    if current:
        chunks.append((current, current_forced))
    return chunks


def build_chunk_artifacts(
    scene: list[dict[str, Any]], target_chars: int, overlap_entries: int
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    primary_chunks = build_primary_chunks(scene, target_chars)
    model_by_id = {str(item.get("id")): model_record(item) for item in scene}
    chunks: list[dict[str, Any]] = []
    files: dict[str, str] = {}
    all_primary_ids: list[str] = []
    for index, (primary, forced) in enumerate(primary_chunks):
        chunk_id = f"chunk-{index + 1:04d}"
        primary_ids = [str(item.get("id")) for item in primary]
        before_ids = (
            [str(item.get("id")) for item in primary_chunks[index - 1][0]][-overlap_entries:]
            if overlap_entries > 0 and index > 0
            else []
        )
        after_ids = (
            [str(item.get("id")) for item in primary_chunks[index + 1][0]][:overlap_entries]
            if overlap_entries > 0 and index + 1 < len(primary_chunks)
            else []
        )
        primary_file = f"chunks/{chunk_id}.source.model.jsonl"
        before_file = f"chunks/{chunk_id}.overlap-before.model.jsonl"
        after_file = f"chunks/{chunk_id}.overlap-after.model.jsonl"
        files[primary_file] = jsonl_text([model_by_id[value] for value in primary_ids])
        files[before_file] = jsonl_text([model_by_id[value] for value in before_ids])
        files[after_file] = jsonl_text([model_by_id[value] for value in after_ids])
        all_primary_ids.extend(primary_ids)
        chunks.append(
            {
                "chunk_id": chunk_id,
                "primary_entry_ids": primary_ids,
                "overlap_before_ids": before_ids,
                "overlap_after_ids": after_ids,
                "primary_source": primary_file,
                "overlap_before_source": before_file,
                "overlap_after_source": after_file,
                "primary_char_count": sum(
                    len(str(item.get("text") or "")) for item in primary
                ),
                "forced_inside_natural_unit": forced,
                "scene_ids": list(
                    dict.fromkeys(
                        str(item.get("scene_id") or item.get("file") or "")
                        for item in primary
                    )
                ),
            }
        )

    expected_ids = [str(item.get("id")) for item in scene]
    counts = Counter(all_primary_ids)
    duplicates = sorted(value for value, count in counts.items() if count != 1)
    missing = [value for value in expected_ids if value not in counts]
    extra = sorted(set(counts) - set(expected_ids))
    coverage = {
        "schema_version": 1,
        "valid": not duplicates and not missing and not extra,
        "planned_entry_count": len(expected_ids),
        "covered_entry_count": len(counts),
        "missing_ids": missing,
        "duplicate_primary_ids": duplicates,
        "extra_ids": extra,
        "assignments": {
            entry_id: chunk["chunk_id"]
            for chunk in chunks
            for entry_id in chunk["primary_entry_ids"]
        },
    }
    plan = {
        "schema_version": 1,
        "target_chars": target_chars,
        "overlap_entries": overlap_entries,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }
    return plan, coverage, files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("job_id")
    parser.add_argument(
        "--max-bundle-chars",
        type=int,
        default=0,
        help="deprecated advisory only; exceeding it no longer invalidates a bundle",
    )
    parser.add_argument("--chunk-target-chars", type=int, default=45000)
    parser.add_argument("--chunk-overlap-entries", type=int, default=8)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--shared-prefix-manifest", type=Path)
    parser.add_argument("--require-shared-prefix", action="store_true")
    parser.add_argument("--standalone", action="store_true")
    args = parser.parse_args()

    if args.chunk_overlap_entries < 0:
        parser.error("--chunk-overlap-entries must be >= 0")
    if args.standalone and args.require_shared_prefix:
        parser.error("--standalone and --require-shared-prefix cannot be combined")

    project = args.project_root.resolve()
    project_data = read_json(project / "project.json", {})
    source_locale = project_data.get("source_locale", "")
    target_locale = project_data.get("target_locale", "")
    jobs = read_jsonl(project / "planning/jobs.jsonl")
    matches = [job for job in jobs if job.get("job_id") == args.job_id]
    if len(matches) != 1:
        parser.error(f"expected one job {args.job_id!r}, found {len(matches)}")
    job = matches[0]

    gate_issues = validate_project(project, "plan-approved")
    if gate_issues:
        parser.error("project is not delegation-ready: " + " | ".join(gate_issues))
    bible_state = read_json(project / "bible/version.json", {})
    if bible_state.get("frozen") is not True:
        parser.error("bible/version.json is not frozen")
    if job.get("bible_version") != bible_state.get("version"):
        parser.error("job bible_version does not match bible/version.json")
    if job.get("plan_approved") is not True:
        parser.error("job plan_approved must be true")

    source_records = read_jsonl(project / "extracted/source.jsonl")
    source_by_id = {item.get("id"): item for item in source_records}
    entry_ids = job.get("entry_ids", [])
    if not isinstance(entry_ids, list) or not entry_ids:
        parser.error("job has no entry_ids")
    missing = [entry_id for entry_id in entry_ids if entry_id not in source_by_id]
    if missing:
        parser.error(f"job references missing source ids: {missing[:10]}")
    scene = [source_by_id[entry_id] for entry_id in entry_ids]
    actual_digest = source_digest(scene)
    if job.get("source_digest") != actual_digest:
        parser.error("job source_digest does not match current source records")

    adjacent_ids = job.get("adjacent_entry_ids", [])
    if not isinstance(adjacent_ids, list):
        parser.error("job adjacent_entry_ids must be an array")
    adjacent_missing = [value for value in adjacent_ids if value not in source_by_id]
    if adjacent_missing:
        parser.error(f"job references missing adjacent ids: {adjacent_missing[:10]}")
    entry_id_set = set(entry_ids)
    adjacent = [source_by_id[value] for value in adjacent_ids if value not in entry_id_set]

    try:
        shared_manifest_path, shared_manifest = resolve_shared_manifest(
            project, args.shared_prefix_manifest, args.standalone
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if args.require_shared_prefix and shared_manifest is None:
        parser.error("no valid shared prefix manifest is available")
    if shared_manifest is not None:
        if shared_manifest.get("bible_version") != job.get("bible_version"):
            parser.error("shared prefix bible_version does not match the job")
        job_decision_digest = str(job.get("decision_snapshot_digest") or "")
        shared_decision = shared_manifest.get("decision_snapshot", {})
        shared_decision_digest = (
            str(shared_decision.get("sha256") or "")
            if isinstance(shared_decision, dict)
            else ""
        )
        if job_decision_digest and job_decision_digest != shared_decision_digest:
            parser.error("job decision snapshot does not match shared prefix")

    scene_model = [model_record(item) for item in scene]
    adjacent_model = [model_record(item) for item in adjacent]
    source_text = jsonl_text(scene)
    adjacent_text = jsonl_text(adjacent)
    source_model_text = jsonl_text(scene_model)
    adjacent_model_text = jsonl_text(adjacent_model)
    source_manifest = {
        "schema_version": 1,
        "job_id": args.job_id,
        "source_digest": actual_digest,
        "records": [machine_record(item) for item in scene],
    }

    chunk_plan, coverage_plan, chunk_files = build_chunk_artifacts(
        scene, args.chunk_target_chars, args.chunk_overlap_entries
    )
    chunk_plan["job_id"] = args.job_id
    chunk_plan["source_digest"] = actual_digest
    coverage_plan["job_id"] = args.job_id
    coverage_plan["source_digest"] = actual_digest
    if coverage_plan.get("valid") is not True:
        parser.error("generated chunk coverage is invalid")
    chunk_plan_text = canonical_json(chunk_plan)
    coverage_plan_text = canonical_json(coverage_plan)

    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else project / "contexts" / args.job_id
    )
    source_output = output_dir / "source.jsonl"
    source_model_output = output_dir / "source.model.jsonl"
    adjacent_output = output_dir / "adjacent.jsonl"
    adjacent_model_output = output_dir / "adjacent.model.jsonl"
    draft_output = project / "translations/drafts" / f"{args.job_id}.jsonl"
    review_output = project / "reviews" / f"{args.job_id}.jsonl"
    route = str(job.get("route") or "unassigned")

    binding: dict[str, Any] = {
        "mode": "shared-prefix" if shared_manifest else "standalone",
        "shared_prefix_manifest": (
            project_relative(project, shared_manifest_path)
            if shared_manifest_path
            else None
        ),
        "shared_prefix_id": shared_manifest.get("prefix_id") if shared_manifest else None,
        "shared_prefix_sha256": (
            shared_manifest.get("prefix_sha256") if shared_manifest else None
        ),
        "decision_snapshot": (
            shared_manifest.get("decision_snapshot") if shared_manifest else None
        ),
    }
    task_data = {
        "job_id": args.job_id,
        "route": route,
        "scene_ids": job.get("scene_ids", []),
        "entry_count": len(scene),
        "source_digest": actual_digest,
        "bible_version": job.get("bible_version"),
        "source_locale": source_locale,
        "target_locale": target_locale,
        "predecessors": job.get("predecessors", []),
        "time": job.get("time", ""),
        "location": job.get("location", ""),
        "prior_summary": job.get("prior_summary", ""),
        "context_notes": job.get("context_notes", ""),
        "job_source_model": project_relative(project, source_model_output),
        "adjacent_source_model": project_relative(project, adjacent_model_output),
        "source_manifest": project_relative(project, output_dir / "source-manifest.json"),
        "chunk_plan": project_relative(project, output_dir / "chunk-plan.json"),
        "coverage_plan": project_relative(project, output_dir / "coverage-plan.json"),
        "draft_output": project_relative(project, draft_output),
        "review_output": project_relative(project, review_output),
    }
    context_parts = [
        f"# Translation job {args.job_id}",
        "## Shared-prefix binding\n\n" + json_block(binding),
        "## Job and boundaries\n\n" + json_block(task_data),
        "## Execution requirements\n\n"
        "In shared-prefix mode, do not reload the Bible, translation contract, "
        "language profile, or decisions; they must already be present in the clean "
        "seed history. Process every primary ID in `chunk-plan.json`. Overlap files "
        "are read-only context and must not be emitted twice. Prefer "
        "`source.model.jsonl` or the corresponding chunk model view; validation and "
        "merge tools restore machine-only fields.",
    ]

    matched_characters = 0
    matched_terms = 0
    if shared_manifest is None:
        scene_text = "\n".join(str(item.get("text") or "") for item in scene)
        speakers = {
            str(item["speaker"])
            for item in scene
            if item.get("speaker") not in (None, "")
        }
        characters = select_characters(
            read_json(project / "bible/characters.json", {}), speakers, scene_text
        )
        voice = select_voice(
            read_json(project / "bible/voice.json", {}), speakers, characters
        )
        glossary = read_glossary(project / "bible/glossary.tsv", scene_text, speakers)
        route_knowledge = select_route_knowledge(
            read_json(project / "bible/route-knowledge.json", {}), route
        )
        calibration = select_calibration(
            project / "bible/calibration.jsonl", speakers, glossary
        )
        skill_root = Path(__file__).resolve().parent.parent
        contract_path = (
            args.contract.resolve()
            if args.contract
            else skill_root / "references/translation-contract.md"
        )
        if not contract_path.is_file():
            parser.error(f"translation contract not found: {contract_path}")
        contract = contract_path.read_text(encoding="utf-8-sig")
        language_profile_path = project / "bible/language-profile.md"
        world_path = project / "bible/world.md"
        honorifics_path = project / "bible/honorifics.md"
        context_parts.extend(
            (
                "## Translation contract\n\n" + contract,
                "## Language-pair profile\n\n"
                + language_profile_path.read_text(encoding="utf-8-sig"),
                "## World and narrative rules\n\n"
                + world_path.read_text(encoding="utf-8-sig"),
                "## Route and current knowledge state\n\n"
                + json_block(route_knowledge),
                "## Address and register policy\n\n"
                + honorifics_path.read_text(encoding="utf-8-sig"),
                "## Character records for this scene\n\n" + json_block(characters),
                "## Voice records for this scene\n\n" + json_block(voice),
                "## Glossary matches for this scene\n\n" + json_block(glossary),
                "## Relevant approved examples\n\n" + json_block(calibration),
            )
        )
        matched_characters = len(characters)
        matched_terms = len(glossary)

    context = "\n\n".join(context_parts).rstrip() + "\n"
    bundle_chars = (
        len(context)
        + len(source_text)
        + len(adjacent_text)
        + len(source_model_text)
        + len(adjacent_model_text)
    )
    warnings: list[str] = []
    if args.max_bundle_chars > 0 and bundle_chars > args.max_bundle_chars:
        warnings.append(
            f"bundle_chars {bundle_chars} exceeds deprecated advisory "
            f"{args.max_bundle_chars}; chunk plan remains valid"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir = output_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    for stale in chunks_dir.glob("*.jsonl"):
        stale.unlink()
    (output_dir / "context.md").write_text(context, encoding="utf-8", newline="\n")
    source_output.write_text(source_text, encoding="utf-8", newline="\n")
    source_model_output.write_text(
        source_model_text, encoding="utf-8", newline="\n"
    )
    adjacent_output.write_text(adjacent_text, encoding="utf-8", newline="\n")
    adjacent_model_output.write_text(
        adjacent_model_text, encoding="utf-8", newline="\n"
    )
    (output_dir / "source-manifest.json").write_text(
        canonical_json(source_manifest), encoding="utf-8", newline="\n"
    )
    (output_dir / "chunk-plan.json").write_text(
        chunk_plan_text, encoding="utf-8", newline="\n"
    )
    (output_dir / "coverage-plan.json").write_text(
        coverage_plan_text, encoding="utf-8", newline="\n"
    )
    for relative, text_value in chunk_files.items():
        path = output_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text_value, encoding="utf-8", newline="\n")

    stale_budget = output_dir / "budget-report.json"
    if stale_budget.exists():
        stale_budget.unlink()
    bundle_status = {
        "schema_version": BUNDLE_SCHEMA,
        "valid": True,
        "job_id": args.job_id,
        "source_digest": actual_digest,
        "bible_version": job.get("bible_version"),
        "shared_prefix_id": binding["shared_prefix_id"],
        "shared_prefix_sha256": binding["shared_prefix_sha256"],
        "skill_name": "translate-visual-novel",
        "skill_revision": SKILL_REVISION,
        "entry_count": len(scene),
        "adjacent_entry_count": len(adjacent),
        "chunk_count": chunk_plan["chunk_count"],
        "chunk_plan_sha256": sha256_text(chunk_plan_text),
        "coverage_plan_sha256": sha256_text(coverage_plan_text),
        "source_model_sha256": sha256_text(source_model_text),
        "bundle_chars": bundle_chars,
        "warnings": warnings,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "bundle-status.json").write_text(
        canonical_json(bundle_status), encoding="utf-8", newline="\n"
    )

    print(
        json.dumps(
            {
                "job_id": args.job_id,
                "context": str(output_dir / "context.md"),
                "source_model": str(source_model_output),
                "entry_count": len(scene),
                "adjacent_entry_count": len(adjacent),
                "chunk_count": chunk_plan["chunk_count"],
                "bundle_chars": bundle_chars,
                "shared_prefix_id": binding["shared_prefix_id"],
                "matched_characters_standalone": matched_characters,
                "matched_terms_standalone": matched_terms,
                "warnings": warnings,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
