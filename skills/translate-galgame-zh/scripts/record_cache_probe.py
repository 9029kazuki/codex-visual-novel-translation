#!/usr/bin/env python3
"""Record per-request usage without mistaking aggregate hits for prefix coverage."""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.dont_write_bytecode = True
from pipeline_common import atomic_text, json_text, load_prefix, read_jsonl


def integer(value, field, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def normalize(row, expected=None, tolerance=0, boundary_kind="text-only"):
    if row.get("usage_scope", "request") != "request":
        raise ValueError("convert cumulative host counters into individual request deltas before recording")
    usage = row.get("usage", row)
    details = usage.get("input_tokens_details", {})
    total = integer(usage.get("input_tokens"), "input_tokens")
    cached = integer(usage.get("cached_input_tokens", details.get("cached_tokens")), "cached_input_tokens", True)
    writes = integer(usage.get("cache_write_tokens", details.get("cache_write_tokens")), "cache_write_tokens", True)
    output = integer(usage.get("output_tokens"), "output_tokens", True)
    if cached is not None and cached > total or writes is not None and writes > total or cached is not None and writes is not None and cached + writes > total:
        raise ValueError("cache read/write counts exceed total input")
    boundary = row.get("rendered_prefix_end_tokens", expected if boundary_kind == "rendered-prefix" else None)
    if boundary is not None:
        integer(boundary, "rendered_prefix_end_tokens")
        if boundary <= 0 or tolerance >= boundary or boundary > total:
            raise ValueError("rendered prefix boundary must be positive, within input, and larger than tolerance")
    passed = None
    if boundary is not None and cached is not None and row.get("request_id"):
        passed = cached >= boundary - tolerance
    return {"request_id": row.get("request_id"), "model": row.get("model"), "worker_id": row.get("worker_id"),
        "cohort": row.get("cohort"), "job_id": row.get("job_id"), "chunk_id": row.get("chunk_id"),
        "history_mode": row.get("history_mode", "unknown"), "reasoning_effort": row.get("reasoning_effort"),
        "input_tokens": total, "cached_input_tokens": cached, "cache_write_tokens": writes,
        "ordinary_input_tokens": total-cached-writes if cached is not None and writes is not None else None,
        "output_tokens": output, "reasoning_tokens": usage.get("output_tokens_details", {}).get("reasoning_tokens"),
        "latency_ms": row.get("latency_ms"), "retry_reason": row.get("retry_reason"),
        "rendered_prefix_end_tokens": boundary, "boundary_passed": passed,
        "verdict": "pass" if passed is True else "fail" if passed is False else "observed-only"}


def aggregate(rows):
    result = {}
    for key in ("input_tokens", "cached_input_tokens", "cache_write_tokens", "ordinary_input_tokens", "output_tokens"):
        result[key] = sum(row[key] for row in rows) if all(row[key] is not None for row in rows) else None
    result["calls"] = len(rows)
    result["cache_rate"] = result["cached_input_tokens"] / result["input_tokens"] if result["input_tokens"] and result["cached_input_tokens"] is not None else None
    statuses = [row["boundary_passed"] for row in rows]
    result["passed"] = False if False in statuses else True if statuses and all(x is True for x in statuses) else None
    result["verdict"] = "pass" if result["passed"] is True else "fail" if result["passed"] is False else "observed-only"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shared_prefix_manifest", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--usage-jsonl", type=Path)
    parser.add_argument("--request-id")
    parser.add_argument("--input-tokens", type=int)
    parser.add_argument("--cached-input-tokens", type=int)
    parser.add_argument("--cache-write-tokens", type=int)
    parser.add_argument("--output-tokens", type=int)
    parser.add_argument("--calls", type=int, default=1, help="legacy option; must be 1, use --usage-jsonl for many requests")
    parser.add_argument("--expected-prefix-tokens", type=int)
    parser.add_argument("--boundary-kind", choices=("text-only", "rendered-prefix"), default="text-only")
    parser.add_argument("--tolerance-tokens", type=int, default=0)
    parser.add_argument("--model")
    parser.add_argument("--history-mode", choices=("seed-all", "clean-none", "inherited-root", "unknown"), default="unknown")
    args = parser.parse_args()
    if args.calls != 1:
        parser.error("aggregate counters cannot prove a single prefix hit; use --usage-jsonl")
    if args.expected_prefix_tokens is not None and args.expected_prefix_tokens <= 0 or args.tolerance_tokens < 0:
        parser.error("expected prefix must be positive and tolerance non-negative")
    if args.expected_prefix_tokens is not None and args.tolerance_tokens >= args.expected_prefix_tokens:
        parser.error("tolerance must be below the prefix boundary")
    try:
        manifest, _ = load_prefix(args.shared_prefix_manifest.resolve())
        if args.output_json.resolve() == args.shared_prefix_manifest.resolve() or args.usage_jsonl and args.output_json.resolve() == args.usage_jsonl.resolve():
            raise ValueError("output must not overwrite an input")
        if args.usage_jsonl:
            raw = read_jsonl(args.usage_jsonl.resolve())
            if not raw or any(not row.get("request_id") for row in raw):
                raise ValueError("usage JSONL requires nonempty per-request IDs")
        else:
            if args.input_tokens is None:
                raise ValueError("provide --input-tokens or --usage-jsonl")
            raw = [{"request_id": args.request_id, "input_tokens": args.input_tokens, "cached_input_tokens": args.cached_input_tokens,
                    "cache_write_tokens": args.cache_write_tokens, "output_tokens": args.output_tokens,
                    "model": args.model, "history_mode": args.history_mode}]
        rows, seen = [], {}
        for item in raw:
            row = normalize(item, args.expected_prefix_tokens, args.tolerance_tokens, args.boundary_kind)
            key = row["request_id"]
            if key and key in seen:
                if seen[key] != row:
                    raise ValueError(f"conflicting duplicate request {key}; do not mix cumulative and request counts")
                continue
            if key:
                seen[key] = row
            rows.append(row)
        report = {"schema_version": 2, "prefix_id": manifest["prefix_id"], "prefix_sha256": manifest["prefix_sha256"],
                  **aggregate(rows), "requests": rows, "best_effort": True,
                  "note": "Coverage concerns a declared full rendered boundary, not a file token count. Host routing and subscription accounting are not established here.",
                  "recorded_at": datetime.now(timezone.utc).isoformat()}
        atomic_text(args.output_json.resolve(), json_text(report))
        print(json.dumps({key: report[key] for key in ("prefix_id", "calls", "verdict", "cache_rate")}, ensure_ascii=False))
        return 1 if report["passed"] is False else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
