#!/usr/bin/env python3
"""Audit stage history and stage-specific evidence for a localization project."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


STAGES = (
    "initialized",
    "researched",
    "roundtrip-proven",
    "extracted",
    "bible-frozen",
    "plan-approved",
    "translating",
    "reviewed",
    "validated",
    "repacked",
    "playtested",
    "released",
)
REQUIRED_RESEARCH_LANES = {"engine", "canon", "target-locale"}
RESEARCH_LANE_ALIASES = {
    "engine": "engine",
    "unpack": "engine",
    "canon": "canon",
    "jp-canon": "canon",
    "target-locale": "target-locale",
    "zh-terminology": "target-locale",
}
SHA256_PATTERN = re.compile(r"sha256:[0-9a-fA-F]{64}\Z")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def read_jsonl(path: Path) -> list[dict[str, Any]] | None:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            for raw in stream:
                if not raw.strip():
                    continue
                value = json.loads(raw)
                if not isinstance(value, dict):
                    return None
                records.append(value)
    except (OSError, json.JSONDecodeError):
        return None
    return records


def directory_has_file(path: Path) -> bool:
    return path.is_dir() and any(item.is_file() for item in path.rglob("*"))


def meaningful_markdown(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return False
    content = [
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#") and line.strip() != "```"
    ]
    return len("".join(content)) >= 10


def passed_report(path: Path) -> bool:
    report = read_json(path)
    return isinstance(report, dict) and report.get("passed") is True


def compute_source_digest(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(str(record.get("id") or "").encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record.get("source_hash") or "").encode("utf-8"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def compute_records_digest(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        text = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest.update(text.encode("utf-8"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def normalized_research_lane(value: Any) -> str:
    return RESEARCH_LANE_ALIASES.get(str(value or ""), "")


def project_schema_version(project: Path) -> int:
    payload = read_json(project / "project.json")
    value = payload.get("schema_version") if isinstance(payload, dict) else 1
    return value if isinstance(value, int) else 1


def sha256_text_file(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_current_shared_prefix(project: Path) -> tuple[list[str], dict[str, Any] | None]:
    issues: list[str] = []
    pointer = read_json(project / "contexts/shared-prefix/current.json")
    if not isinstance(pointer, dict) or not pointer.get("manifest"):
        return ["contexts/shared-prefix/current.json is missing or invalid"], None
    manifest_path = Path(str(pointer["manifest"]))
    if not manifest_path.is_absolute():
        manifest_path = project / manifest_path
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        return [f"shared prefix manifest is invalid: {manifest_path}"], None
    prefix_path = manifest_path.parent / "shared-prefix.md"
    actual_prefix = sha256_text_file(prefix_path)
    expected_prefix = str(manifest.get("prefix_sha256") or "")
    if actual_prefix != expected_prefix:
        issues.append("shared prefix text digest does not match its manifest")
    if pointer.get("prefix_id") != manifest.get("prefix_id"):
        issues.append("shared prefix pointer prefix_id does not match its manifest")
    if pointer.get("prefix_sha256") != expected_prefix:
        issues.append("shared prefix pointer digest does not match its manifest")
    sections = manifest.get("sections")
    if not isinstance(sections, list) or not sections:
        issues.append("shared prefix manifest has no sections")
    else:
        for item in sections:
            if not isinstance(item, dict) or not item.get("file"):
                issues.append("shared prefix manifest contains an invalid section")
                break
            section_path = manifest_path.parent / str(item["file"])
            if sha256_text_file(section_path) != item.get("sha256"):
                issues.append(f"shared prefix section digest mismatch: {item.get('file')}")
                break
    return issues, manifest


def validate_history(state: Any, expected_stage: str | None = None) -> list[str]:
    issues: list[str] = []
    if not isinstance(state, dict):
        return ["run-state.json is missing or invalid"]
    stage = state.get("stage")
    if stage not in STAGES:
        return [f"run-state stage is invalid: {stage!r}"]
    if expected_stage is not None and stage != expected_stage:
        issues.append(f"run-state stage is {stage!r}, expected {expected_stage!r}")
    history = state.get("history")
    if not isinstance(history, list):
        return issues + ["run-state history must be an array"]
    required = list(STAGES[: STAGES.index(stage) + 1])
    actual = [entry.get("stage") for entry in history if isinstance(entry, dict)]
    if actual != required:
        issues.append(f"stage history must be contiguous {required}, found {actual}")
    for index, entry in enumerate(history):
        if not isinstance(entry, dict):
            issues.append(f"history entry {index} is not an object")
            continue
        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            issues.append(f"history entry {entry.get('stage')!r} has no evidence list")
    return issues


def validate_gate(project: Path, stage: str) -> list[str]:
    issues: list[str] = []
    if stage not in STAGES:
        return [f"unknown stage: {stage}"]

    if stage == "initialized":
        project_data = read_json(project / "project.json")
        if not isinstance(project_data, dict) or not project_data.get("game_name"):
            issues.append("project.json must contain game_name")
        elif project_schema_version(project) >= 3:
            source_locale = project_data.get("source_locale")
            target_locale = project_data.get("target_locale")
            if not isinstance(source_locale, str) or not source_locale:
                issues.append("project.json must contain source_locale")
            if not isinstance(target_locale, str) or not target_locale:
                issues.append("project.json must contain target_locale")
            if (
                isinstance(source_locale, str)
                and isinstance(target_locale, str)
                and source_locale.casefold() == target_locale.casefold()
            ):
                issues.append("source_locale and target_locale must be different")

    elif stage == "researched":
        manifest = read_json(project / "source/file-manifest.json")
        if not isinstance(manifest, dict) or not manifest.get("file_count"):
            issues.append("source/file-manifest.json must describe at least one source file")
        sources = read_jsonl(project / "research/sources.jsonl")
        if sources is None:
            issues.append("research/sources.jsonl is invalid")
        else:
            lanes = {normalized_research_lane(item.get("lane")) for item in sources}
            missing_lanes = sorted(REQUIRED_RESEARCH_LANES - lanes)
            if missing_lanes:
                issues.append(f"research sources are missing lanes: {missing_lanes}")
            require_rich_source_schema = project_schema_version(project) >= 2
            for item in sources:
                claims = item.get("claims")
                if (
                    not item.get("url")
                    or not item.get("title")
                    or not normalized_research_lane(item.get("lane"))
                    or not isinstance(claims, list)
                    or not claims
                ):
                    issues.append(
                        "every research source needs url, title, a known lane, and non-empty claims"
                    )
                    break
                source_language = item.get("source_language") or item.get("language")
                if require_rich_source_schema and (
                    not source_language
                    or not item.get("source_type")
                    or not item.get("authority")
                    or not item.get("retrieved_at")
                    or not item.get("scope")
                    or item.get("confidence") not in {"high", "medium", "low"}
                ):
                    issues.append(
                        "schema v2 research sources need source_language, source_type, "
                        "authority, retrieved_at, scope, and valid confidence"
                    )
                    break
        if not meaningful_markdown(project / "research/unpack-notes.md"):
            issues.append("research/unpack-notes.md has no meaningful result")

    elif stage == "roundtrip-proven":
        if not passed_report(project / "qa/roundtrip-report.json"):
            issues.append("qa/roundtrip-report.json must contain passed=true")
        for relative in (
            "staging/roundtrip/input",
            "staging/roundtrip/unpacked",
            "staging/roundtrip/repacked",
        ):
            if not directory_has_file(project / relative):
                issues.append(f"{relative} contains no proof file")

    elif stage == "extracted":
        source = read_jsonl(project / "extracted/source.jsonl")
        if not source:
            issues.append("extracted/source.jsonl has no records")
        else:
            ids = [item.get("id") for item in source]
            if any(not isinstance(value, str) or not value for value in ids):
                issues.append("every extracted record needs a string id")
            if len(ids) != len(set(ids)):
                issues.append("extracted source ids are not unique")
            if any(
                not isinstance(item.get("source_hash"), str)
                or not SHA256_PATTERN.fullmatch(item["source_hash"])
                for item in source
            ):
                issues.append("every extracted record needs a valid sha256 source_hash")
            for item in source:
                if not isinstance(item.get("text"), str):
                    issues.append(f"extracted record {item.get('id')} needs string text")
                if not isinstance(item.get("file"), str) or not item.get("file"):
                    issues.append(f"extracted record {item.get('id')} needs source file")
                if not isinstance(item.get("order"), int):
                    issues.append(f"extracted record {item.get('id')} needs integer order")
                tokens = item.get("protected_tokens")
                if not isinstance(tokens, list) or any(
                    not isinstance(token, str) for token in tokens
                ):
                    issues.append(
                        f"extracted record {item.get('id')} needs string-array protected_tokens"
                    )
        script_map = read_json(project / "extracted/script-map.json")
        if (
            not isinstance(script_map, dict)
            or not isinstance(script_map.get("nodes"), list)
            or not script_map["nodes"]
        ):
            issues.append("extracted/script-map.json has no scene nodes")
        token_report = read_json(project / "extracted/control-token-report.json")
        if (
            not isinstance(token_report, dict)
            or not isinstance(token_report.get("engines"), list)
            or not token_report["engines"]
        ):
            issues.append("extracted/control-token-report.json has no engine inventory")

    elif stage == "bible-frozen":
        version = read_json(project / "bible/version.json")
        if (
            not isinstance(version, dict)
            or version.get("frozen") is not True
            or not isinstance(version.get("version"), int)
            or version["version"] < 1
        ):
            issues.append("bible/version.json must be frozen at version >= 1")
        if not meaningful_markdown(project / "bible/world.md"):
            issues.append("bible/world.md has no meaningful content")
        if not meaningful_markdown(project / "bible/honorifics.md"):
            issues.append("bible/honorifics.md has no meaningful policy")
        if project_schema_version(project) >= 3 and not meaningful_markdown(
            project / "bible/language-profile.md"
        ):
            issues.append("bible/language-profile.md has no meaningful policy")
        characters = read_json(project / "bible/characters.json")
        if (
            not isinstance(characters, dict)
            or not isinstance(characters.get("characters"), list)
            or not characters["characters"]
            or any(not isinstance(item, dict) for item in characters["characters"])
        ):
            issues.append("bible/characters.json has no characters")
        voice = read_json(project / "bible/voice.json")
        if (
            not isinstance(voice, dict)
            or not isinstance(voice.get("characters", {}), dict)
            or not isinstance(voice.get("narrator", {}), dict)
            or not (voice.get("characters") or voice.get("narrator"))
        ):
            issues.append("bible/voice.json has no voice definitions")
        route_knowledge = read_json(project / "bible/route-knowledge.json")
        if (
            not isinstance(route_knowledge, dict)
            or not isinstance(route_knowledge.get("global", {}), dict)
            or not isinstance(route_knowledge.get("routes", {}), dict)
        ):
            issues.append("bible/route-knowledge.json is invalid")
        calibration = read_jsonl(project / "bible/calibration.jsonl")
        if not calibration:
            issues.append("bible/calibration.jsonl has no approved examples")
        glossary_path = project / "bible/glossary.tsv"
        try:
            with glossary_path.open("r", encoding="utf-8-sig", newline="") as stream:
                glossary_reader = csv.DictReader(stream, delimiter="\t")
                glossary = list(glossary_reader)
                glossary_fields = set(glossary_reader.fieldnames or [])
        except OSError:
            glossary = []
            glossary_fields = set()
        if not glossary:
            issues.append("bible/glossary.tsv has no terminology rows")
        required_glossary_fields = {
            "source",
            "target",
            "reading",
            "category",
            "status",
            "scope",
            "source_url",
            "notes",
        }
        if not required_glossary_fields.issubset(glossary_fields):
            issues.append("bible/glossary.tsv is missing required columns")

    elif stage == "plan-approved":
        jobs = read_jsonl(project / "planning/jobs.jsonl")
        source = read_jsonl(project / "extracted/source.jsonl")
        version = read_json(project / "bible/version.json")
        script_map = read_json(project / "extracted/script-map.json")
        if not jobs:
            issues.append("planning/jobs.jsonl has no jobs")
        elif not source:
            issues.append("cannot validate job coverage without extracted source")
        else:
            bible_version = version.get("version") if isinstance(version, dict) else None
            source_by_id = {str(item.get("id")): item for item in source}
            raw_job_ids = [job.get("job_id") for job in jobs]
            if any(not isinstance(value, str) or not value for value in raw_job_ids):
                issues.append("every plan job needs a non-empty string job_id")
            job_id_values = [value if isinstance(value, str) else "" for value in raw_job_ids]
            duplicate_job_ids = sorted(
                value for value, count in Counter(job_id_values).items() if value and count > 1
            )
            if duplicate_job_ids:
                issues.append(f"duplicate job_id values: {duplicate_job_ids[:10]}")
            job_ids = set(job_id_values)
            graph_pairs: set[tuple[str, str]] = set()
            if isinstance(script_map, dict) and isinstance(script_map.get("edges"), list):
                for edge in script_map["edges"]:
                    if not isinstance(edge, dict):
                        continue
                    left = str(edge.get("from") or edge.get("source") or "")
                    right = str(edge.get("to") or edge.get("target") or "")
                    if left and right:
                        graph_pairs.add((left, right))
                        graph_pairs.add((right, left))
            coverage: list[str] = []
            for job in jobs:
                if job.get("plan_approved") is not True:
                    issues.append(f"job {job.get('job_id')} is not plan_approved")
                if job.get("bible_version") != bible_version:
                    issues.append(f"job {job.get('job_id')} has stale bible_version")
                entry_ids = job.get("entry_ids", [])
                if isinstance(entry_ids, list):
                    digest_records = [
                        source_by_id[str(entry_id)]
                        for entry_id in entry_ids
                        if str(entry_id) in source_by_id
                    ]
                    if len(digest_records) == len(entry_ids):
                        expected_digest = compute_source_digest(digest_records)
                        if job.get("source_digest") != expected_digest:
                            issues.append(
                                f"job {job.get('job_id')} source_digest does not match its source records"
                            )
                    elif not SHA256_PATTERN.fullmatch(str(job.get("source_digest") or "")):
                        issues.append(f"job {job.get('job_id')} has invalid source_digest")
                if not str(job.get("context_notes") or "").strip():
                    issues.append(f"job {job.get('job_id')} has empty context_notes")
                for field in ("entry_ids", "scene_ids", "source_files"):
                    if not isinstance(job.get(field), list) or not job.get(field):
                        issues.append(
                            f"job {job.get('job_id')} field {field} must be a non-empty array"
                        )
                    elif any(
                        not isinstance(value, str) or not value for value in job[field]
                    ):
                        issues.append(
                            f"job {job.get('job_id')} field {field} must contain non-empty strings"
                        )
                for field in ("predecessors", "adjacent_entry_ids"):
                    if not isinstance(job.get(field), list):
                        issues.append(f"job {job.get('job_id')} field {field} must be an array")
                    elif any(
                        not isinstance(value, str) or not value for value in job[field]
                    ):
                        issues.append(
                            f"job {job.get('job_id')} field {field} must contain non-empty strings"
                        )
                if isinstance(job.get("entry_ids"), list):
                    coverage.extend(str(value) for value in job["entry_ids"])
                predecessors = job.get("predecessors", [])
                if isinstance(predecessors, list):
                    unknown_predecessors = [
                        value for value in predecessors if str(value) not in job_ids
                    ]
                    if unknown_predecessors:
                        issues.append(
                            f"job {job.get('job_id')} has unknown predecessors {unknown_predecessors}"
                        )
                adjacent_ids = job.get("adjacent_entry_ids", [])
                current_scenes = {str(value) for value in job.get("scene_ids", [])}
                if isinstance(adjacent_ids, list):
                    for adjacent_id in adjacent_ids:
                        adjacent_record = source_by_id.get(str(adjacent_id))
                        if adjacent_record is None:
                            issues.append(
                                f"job {job.get('job_id')} has unknown adjacent id {adjacent_id}"
                            )
                            continue
                        adjacent_scene = str(
                            adjacent_record.get("scene_id")
                            or adjacent_record.get("file")
                            or ""
                        )
                        if adjacent_scene not in current_scenes and not any(
                            (scene, adjacent_scene) in graph_pairs for scene in current_scenes
                        ):
                            issues.append(
                                f"job {job.get('job_id')} adjacent id {adjacent_id} is not connected in script-map"
                            )
            source_ids = [str(item.get("id")) for item in source]
            counts = Counter(coverage)
            if set(counts) != set(source_ids):
                missing = sorted(set(source_ids) - set(counts))
                extra = sorted(set(counts) - set(source_ids))
                issues.append(f"job coverage mismatch; missing={missing[:10]}, extra={extra[:10]}")
            overlaps = sorted(entry_id for entry_id, count in counts.items() if count != 1)
            if overlaps:
                issues.append(f"job entry overlap detected: {overlaps[:10]}")

    elif stage == "translating":
        jobs = read_jsonl(project / "planning/jobs.jsonl") or []
        active = {"assigned", "translated", "validated", "reviewed", "approved", "merged"}
        active_jobs = [job for job in jobs if job.get("status") in active]
        if not active_jobs:
            issues.append("no job has entered translation")
        if project_schema_version(project) >= 2:
            prefix_issues, prefix_manifest = validate_current_shared_prefix(project)
            issues.extend(prefix_issues)
            prefix_id = (
                prefix_manifest.get("prefix_id") if isinstance(prefix_manifest, dict) else None
            )
            prefix_digest = (
                prefix_manifest.get("prefix_sha256")
                if isinstance(prefix_manifest, dict)
                else None
            )
            for job in active_jobs:
                job_id = str(job.get("job_id") or "")
                status = read_json(project / "contexts" / job_id / "bundle-status.json")
                if not isinstance(status, dict) or status.get("valid") is not True:
                    issues.append(f"job {job_id} has no valid bundle-status.json")
                    continue
                if status.get("source_digest") != job.get("source_digest"):
                    issues.append(f"job {job_id} bundle source_digest is stale")
                if status.get("bible_version") != job.get("bible_version"):
                    issues.append(f"job {job_id} bundle bible_version is stale")
                if status.get("shared_prefix_id") != prefix_id:
                    issues.append(f"job {job_id} bundle uses a different shared prefix")
                if status.get("shared_prefix_sha256") != prefix_digest:
                    issues.append(f"job {job_id} bundle shared prefix digest is stale")
                coverage = read_json(project / "contexts" / job_id / "coverage-plan.json")
                if not isinstance(coverage, dict) or coverage.get("valid") is not True:
                    issues.append(f"job {job_id} coverage-plan.json is invalid")

    elif stage == "reviewed":
        jobs = read_jsonl(project / "planning/jobs.jsonl") or []
        complete = {"reviewed", "approved", "merged"}
        for job in jobs:
            if job.get("status") not in complete:
                issues.append(f"job {job.get('job_id')} is not reviewed")
            if not (project / "reviews" / f"{job.get('job_id')}.jsonl").exists():
                issues.append(f"job {job.get('job_id')} has no review artifact")
            if project_schema_version(project) >= 2:
                report = read_json(
                    project / "reviews" / f"{job.get('job_id')}.report.json"
                )
                draft = read_jsonl(
                    project / "translations/drafts" / f"{job.get('job_id')}.jsonl"
                )
                if (
                    not isinstance(report, dict)
                    or report.get("passed") is not True
                    or report.get("coverage") != "all-entries"
                    or report.get("reviewed_source_digest") != job.get("source_digest")
                    or report.get("reviewed_entry_count") != len(job.get("entry_ids", []))
                    or not isinstance(draft, list)
                    or report.get("reviewed_draft_digest") != compute_records_digest(draft)
                ):
                    issues.append(
                        f"job {job.get('job_id')} has no valid all-entry sparse review report"
                    )

    elif stage == "validated":
        jobs = read_jsonl(project / "planning/jobs.jsonl") or []
        if any(job.get("status") not in {"approved", "merged"} for job in jobs):
            issues.append("all jobs must be approved or merged")
        report = read_json(project / "qa/global.json")
        if not isinstance(report, dict) or report.get("errors") != 0:
            issues.append("qa/global.json must report errors=0")

    elif stage == "repacked":
        if not directory_has_file(project / "build"):
            issues.append("build directory contains no repacked output")
        if not passed_report(project / "qa/repack-report.json"):
            issues.append("qa/repack-report.json must contain passed=true")

    elif stage == "playtested":
        if not passed_report(project / "qa/playtest-report.json"):
            issues.append("qa/playtest-report.json must contain passed=true")

    elif stage == "released":
        if not directory_has_file(project / "release"):
            issues.append("release directory contains no files")
        if not passed_report(project / "qa/release-report.json"):
            issues.append("qa/release-report.json must contain passed=true")

    return issues


def validate_project(project: Path, through_stage: str) -> list[str]:
    state = read_json(project / "run-state.json")
    issues = validate_history(state)
    if not isinstance(state, dict) or state.get("stage") not in STAGES:
        return issues
    if STAGES.index(state["stage"]) < STAGES.index(through_stage):
        issues.append(
            f"project is at {state.get('stage')!r}, below required stage {through_stage!r}"
        )
        return issues
    history = state.get("history", [])
    if isinstance(history, list):
        for entry in history:
            if not isinstance(entry, dict):
                continue
            for evidence in entry.get("evidence", []):
                path = Path(str(evidence))
                path = path if path.is_absolute() else project / path
                if not path.exists():
                    issues.append(
                        f"history stage {entry.get('stage')!r} references missing evidence {evidence!r}"
                    )
    for stage in STAGES[: STAGES.index(through_stage) + 1]:
        issues.extend(f"{stage}: {message}" for message in validate_gate(project, stage))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--through-stage", choices=STAGES)
    args = parser.parse_args()

    project = args.project_root.resolve()
    state = read_json(project / "run-state.json")
    stage = args.through_stage or (state.get("stage") if isinstance(state, dict) else None)
    if stage not in STAGES:
        parser.error("cannot determine a valid target stage")
    issues = validate_project(project, stage)
    result = {"project": str(project), "through_stage": stage, "valid": not issues, "issues": issues}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
