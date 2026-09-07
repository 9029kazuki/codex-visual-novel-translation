#!/usr/bin/env python3
"""Build immutable, budgeted job snapshots; --jobs/--all-pending shares one read snapshot."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
from audit_project import validate_project
from pipeline_common import (REVISION, TokenCounter, atomic_text, digest_text, digest_value,
    inside, json_text, load_prefix, load_semantics, read_json, read_jsonl, read_snapshot,
    read_text, scoped_semantics, job_contract_digest)

MODEL_FIELDS = ("id", "kind", "speaker", "text", "protected_tokens")


def source_digest(records):
    digest = hashlib.sha256()
    for record in records:
        digest.update(str(record.get("id") or "").encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record.get("source_hash") or "").encode("utf-8"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def model_record(record):
    value = {"id": record["id"], "kind": record.get("kind", record.get("type", "")),
             "speaker": record.get("speaker", ""), "text": record["text"]}
    if record.get("protected_tokens"):
        value["protected_tokens"] = record["protected_tokens"]
    return value


def jsonl_text(rows):
    return "".join(json_text(row) for row in rows)


def project_relative(project, path):
    try:
        return path.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def packet(context, primary, before, after, adjacent, chunk_id):
    return {"chunk_id": chunk_id, "context": context, "primary": [model_record(x) for x in primary],
            "overlap_before": [model_record(x) for x in before], "overlap_after": [model_record(x) for x in after],
            "adjacent": [model_record(x) for x in adjacent]}


def build_chunk_artifacts(scene, target_chars=45000, overlap_entries=8, *, counter=None,
                          input_budget=32000, output_reserve=8192, prefix_tokens=0,
                          fixed_overhead=0, context="", adjacent=None):
    counter = counter or TokenCounter()
    adjacent = adjacent or []
    if not scene or overlap_entries < 0 or input_budget <= 0 or output_reserve <= 0:
        raise ValueError("nonempty scene and positive budgets are required")
    ids = [row["id"] for row in scene]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate source IDs")
    empty_tokens = counter.count(json_text(packet(context, [], [], [], adjacent, "chunk-0000")))
    room = input_budget - prefix_tokens - fixed_overhead - empty_tokens
    if room <= 0:
        raise ValueError(f"shared prefix/context exhausts input budget {input_budget}; choose an approved smaller profile or explicit larger budget")
    in_sizes = [counter.count(json_text(model_record(row))) + 4 for row in scene]
    out_sizes = [max(1, int(counter.count(json_text({"id": row["id"], "translation": row["text"]})) * 1.5)) for row in scene]
    ranges, start, used, out, chars = [], 0, 0, 0, 0
    for i, row in enumerate(scene):
        size = len(row["text"])
        overflow = used + in_sizes[i] > room or out + out_sizes[i] > output_reserve or (target_chars > 0 and chars + size > target_chars)
        boundary = i > start and (row.get("boundary_before") or row.get("scene_id") != scene[i-1].get("scene_id"))
        if i > start and (overflow or boundary):
            ranges.append((start, i))
            start, used, out, chars = i, 0, 0, 0
        used += in_sizes[i]
        out += out_sizes[i]
        chars += size
        if in_sizes[i] > room or out_sizes[i] > output_reserve:
            raise ValueError(f"single entry {row['id']} exceeds planning budget; resolve the long entry explicitly")
    ranges.append((start, len(scene)))
    chunks, files = [], {}
    for index, (left, right) in enumerate(ranges):
        chunk_id = f"chunk-{index+1:04d}"
        primary = scene[left:right]
        before = scene[max(0, left-overlap_entries):left]
        after = scene[right:right+overlap_entries]
        original_overlap = len(before) + len(after)
        while True:
            value = packet(context, primary, before, after, adjacent, chunk_id)
            input_tokens = prefix_tokens + fixed_overhead + counter.count(json_text(value))
            if input_tokens <= input_budget:
                break
            if before or after:
                if len(before) >= len(after):
                    before = before[1:]
                else:
                    after = after[:-1]
            else:
                raise ValueError(f"serialized packet {chunk_id} exceeds planning budget ({input_tokens}>{input_budget})")
        primary_path = f"chunks/{chunk_id}.source.model.jsonl"
        before_path = f"chunks/{chunk_id}.overlap-before.model.jsonl"
        after_path = f"chunks/{chunk_id}.overlap-after.model.jsonl"
        packet_path = f"chunks/{chunk_id}.packet.json"
        files[primary_path] = jsonl_text([model_record(x) for x in primary])
        files[before_path] = jsonl_text([model_record(x) for x in before])
        files[after_path] = jsonl_text([model_record(x) for x in after])
        files[packet_path] = json_text(value)
        chunks.append({"chunk_id": chunk_id, "primary_entry_ids": [x["id"] for x in primary],
            "overlap_before_ids": [x["id"] for x in before], "overlap_after_ids": [x["id"] for x in after],
            "primary_source": primary_path, "overlap_before_source": before_path, "overlap_after_source": after_path,
            "packet": packet_path, "estimated_input_tokens": input_tokens, "estimated_output_tokens": sum(out_sizes[left:right]),
            "overlap_reduced_for_budget": len(before)+len(after) < original_overlap,
            "forced_inside_natural_unit": bool(left and not scene[left].get("boundary_before") and scene[left].get("scene_id") == scene[left-1].get("scene_id")),
            "primary_char_count": sum(len(x["text"]) for x in primary)})
    coverage = {"schema_version": 2, "valid": True, "planned_entry_count": len(ids), "covered_entry_count": len(ids),
                "missing_ids": [], "duplicate_primary_ids": [], "extra_ids": [],
                "assignments": {entry: chunk["chunk_id"] for chunk in chunks for entry in chunk["primary_entry_ids"]}}
    plan = {"schema_version": 2, "chunk_count": len(chunks), "target_chars": target_chars, "overlap_entries": overlap_entries,
            "token_method": counter.method, "input_budget_tokens": input_budget, "output_reserve_tokens": output_reserve, "chunks": chunks}
    return plan, coverage, files


def resolve_manifest(project, explicit):
    if explicit:
        return explicit.resolve()
    pointer = read_json(project / "contexts/shared-prefix/current.json")
    path = Path(pointer["manifest"])
    return path if path.is_absolute() else project / path


def build_job(project, job, args, source_by_id, counter):
    job_id = job["job_id"]
    if job.get("plan_approved") is not True:
        raise ValueError(f"job {job_id} is not approved")
    scene = [source_by_id[x] for x in job["entry_ids"]]
    if source_digest(scene) != job.get("source_digest"):
        raise ValueError(f"job {job_id} source digest changed")
    selected = set(job["entry_ids"])
    adjacent = [source_by_id[x] for x in dict.fromkeys(job.get("adjacent_entry_ids", [])) if x not in selected]
    manifest_path = resolve_manifest(project, args.shared_prefix_manifest)
    manifest, frozen = load_prefix(manifest_path)
    if frozen is None:
        raise ValueError("rebuild the shared prefix with v3 before building jobs")
    # The profile is an approved closure; a per-job subset may only narrow it
    # when the coordinator has explicitly approved that subset.
    scope = job.get("dependency_scope") or manifest.get("profile") or {"mode": "project"}
    dependency = scoped_semantics(frozen, scope)
    decisions_path = Path(manifest.get("live_decisions_source") or manifest["decision_snapshot"]["source"])
    if not decisions_path.is_absolute():
        decisions_path = project / decisions_path
    current = load_semantics(project, Path(manifest["contract_source"]), decisions_path)
    if digest_value(scoped_semantics(current, scope)) != digest_value(dependency):
        raise ValueError(f"job {job_id} selected prefix is stale for its semantic dependencies")
    if job.get("decision_snapshot_digest") and job["decision_snapshot_digest"] != manifest["decision_snapshot"]["sha256"]:
        raise ValueError("job decision digest differs; explicitly migrate the legacy/raw decision binding")
    context_data = {key: job.get(key, "") for key in ("job_id", "route", "scene_ids", "time", "location", "prior_summary", "context_notes", "predecessors")}
    context_data.update({"primary_only": True, "draft_output": f"translations/drafts/{job_id}.jsonl",
                         "review_output": f"reviews/{job_id}.jsonl", "shared_prefix_id": manifest["prefix_id"]})
    context = json_text(context_data)
    prefix_text = read_text(manifest_path.parent / "shared-prefix.md")
    if args.standalone:
        context += "\n" + prefix_text
    prefix_tokens = 0 if args.standalone else counter.count(prefix_text)
    effective_budget = args.input_budget_tokens
    if args.context_window_tokens:
        effective_budget = min(effective_budget, args.context_window_tokens - args.output_reserve_tokens)
    plan, coverage, chunk_files = build_chunk_artifacts(scene, args.chunk_target_chars, args.chunk_overlap_entries,
        counter=counter, input_budget=effective_budget, output_reserve=args.output_reserve_tokens,
        prefix_tokens=prefix_tokens, fixed_overhead=args.fixed_overhead_tokens, context=context, adjacent=adjacent)
    plan.update(job_id=job_id, source_digest=job["source_digest"])
    coverage.update(job_id=job_id, source_digest=job["source_digest"])
    machine = {"schema_version": 2, "job_id": job_id, "source_digest": job["source_digest"],
               "records": [{key: row.get(key) for key in ("id", "source_hash", "file", "order", "route", "scene_id")} for row in scene]}
    artifacts = {"context.md": context, "source.jsonl": jsonl_text(scene), "source.model.jsonl": jsonl_text([model_record(x) for x in scene]),
                 "adjacent.jsonl": jsonl_text(adjacent), "adjacent.model.jsonl": jsonl_text([model_record(x) for x in adjacent]),
                 "source-manifest.json": json_text(machine), "chunk-plan.json": json_text(plan), "coverage-plan.json": json_text(coverage), **chunk_files}
    artifact_hashes = {key: digest_text(value) for key, value in artifacts.items()}
    warnings = ["Counts are planning estimates; confirm host input/history and output limits before dispatch."]
    if not args.context_window_tokens:
        warnings.append("Host context capacity was not supplied; only the configured planning cap is checked.")
    status = {"schema_version": 3, "skill_revision": REVISION, "valid": True, "job_id": job_id,
        "source_digest": job["source_digest"], "bible_version": job.get("bible_version"),
        "shared_prefix_id": manifest["prefix_id"], "shared_prefix_sha256": manifest["prefix_sha256"],
        "shared_prefix_manifest": project_relative(project, manifest_path), "mode": "standalone" if args.standalone else "shared-prefix",
        "dependency_scope": scope, "dependency_digest": digest_value(dependency), "entry_count": len(scene),
        "job_contract_digest": job_contract_digest(job), "input_records_digest": digest_value({"scene": scene, "adjacent": adjacent}),
        "adjacent_entry_count": len(adjacent), "chunk_count": plan["chunk_count"], "artifacts": artifact_hashes,
        "budget": {"planning_passed": True, "host_capacity_supplied": bool(args.context_window_tokens),
            "actual_usage_verified": False, "token_method": counter.method, "input_budget_tokens": effective_budget,
            "output_reserve_tokens": args.output_reserve_tokens, "fixed_overhead_tokens": args.fixed_overhead_tokens,
            "prefix_tokens": prefix_tokens, "max_packet_input_tokens": max(x["estimated_input_tokens"] for x in plan["chunks"])},
        "artifact_bytes": sum(len(value.encode("utf-8")) for value in artifacts.values()), "warnings": warnings}
    snapshot_id = digest_value(status).split(":")[1][:24]
    output = args.output_dir.resolve() if args.output_dir else inside(project / "contexts", job_id)
    destination = output / "snapshots" / snapshot_id
    # Content-addressed files are never overwritten. The one pointer is published
    # only after every artifact exists and has been read back successfully.
    for relative, text in {**artifacts, "bundle-status.json": json_text(status)}.items():
        path = inside(destination, relative)
        if path.exists() and path.read_text(encoding="utf-8-sig") != text:
            raise ValueError(f"immutable bundle differs: {path}")
        if not path.exists():
            atomic_text(path, text)
        if digest_text(path.read_text(encoding="utf-8-sig")) != digest_text(text):
            raise ValueError(f"bundle write verification failed: {path}")
    atomic_text(output / "current.json", json_text({"schema_version": 1, "snapshot": f"snapshots/{snapshot_id}",
                "status_sha256": digest_text(json_text(status))}))
    return {"job_id": job_id, "snapshot": str(destination), "entry_count": len(scene), "chunk_count": plan["chunk_count"],
            "shared_prefix_id": manifest["prefix_id"], "budget": status["budget"], "warnings": warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("job_id", nargs="?")
    parser.add_argument("--jobs", nargs="+")
    parser.add_argument("--all-pending", action="store_true")
    parser.add_argument("--chunk-target-chars", type=int, default=45000)
    parser.add_argument("--chunk-overlap-entries", type=int, default=8)
    parser.add_argument("--input-budget-tokens", type=int, default=32000, help="planning cap, not a claim about the host window")
    parser.add_argument("--output-reserve-tokens", type=int, default=8192)
    parser.add_argument("--fixed-overhead-tokens", type=int, default=0, help="observed host instructions/tools/history budget allocation")
    parser.add_argument("--context-window-tokens", type=int)
    parser.add_argument("--encoding", help="optional tiktoken encoding; still labeled a proxy")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--shared-prefix-manifest", type=Path)
    parser.add_argument("--require-shared-prefix", action="store_true", help="compatibility flag; v3 always binds a frozen prefix")
    parser.add_argument("--standalone", action="store_true")
    parser.add_argument("--max-bundle-chars", type=int, default=0, help="deprecated; use token planning caps")
    args = parser.parse_args()
    if sum(bool(x) for x in (args.job_id, args.jobs, args.all_pending)) != 1:
        parser.error("choose one job_id, --jobs, or --all-pending")
    if args.fixed_overhead_tokens < 0 or args.chunk_overlap_entries < 0 or min(args.input_budget_tokens, args.output_reserve_tokens) <= 0:
        parser.error("invalid budget or overlap")
    if args.context_window_tokens is not None and args.context_window_tokens <= args.output_reserve_tokens:
        parser.error("context window must exceed output reserve")
    try:
        project = args.project_root.resolve()
        counter = TokenCounter(args.encoding)
        with read_snapshot() as stats:
            issues = validate_project(project, "plan-approved")
            if issues:
                raise ValueError(" | ".join(issues))
            jobs = read_jsonl(project / "planning/jobs.jsonl")
            wanted = set(args.jobs or ([args.job_id] if args.job_id else [j["job_id"] for j in jobs if j.get("status") == "pending"]))
            if not wanted or wanted - {j["job_id"] for j in jobs}:
                raise ValueError("no matching jobs, or unknown requested job IDs")
            if args.output_dir and len(wanted) != 1:
                raise ValueError("--output-dir requires exactly one job")
            sources = {row["id"]: row for row in read_jsonl(project / "extracted/source.jsonl")}
            results = [build_job(project, job, args, sources, counter) for job in jobs if job["job_id"] in wanted]
        print(json.dumps({"jobs": results, "input_snapshot": {key: stats[key] for key in ("physical_reads", "file_cache_misses", "verification_reads", "parsed_jsonl_records")}}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
