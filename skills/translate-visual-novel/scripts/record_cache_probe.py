#!/usr/bin/env python3
"""Record a best-effort shared-prefix cache probe from observed usage counters."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shared_prefix_manifest", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--input-tokens", type=int, required=True)
    parser.add_argument("--cached-input-tokens", type=int, required=True)
    parser.add_argument("--output-tokens", type=int, default=0)
    parser.add_argument("--calls", type=int, default=1)
    parser.add_argument("--expected-prefix-tokens", type=int)
    parser.add_argument("--tolerance-tokens", type=int, default=256)
    parser.add_argument("--model", default="")
    parser.add_argument(
        "--history-mode",
        choices=("seed-all", "clean-none", "inherited-root", "unknown"),
        default="seed-all",
    )
    args = parser.parse_args()

    if min(
        args.input_tokens,
        args.cached_input_tokens,
        args.output_tokens,
        args.calls,
        args.tolerance_tokens,
    ) < 0:
        parser.error("usage counts and tolerance must be non-negative")
    if args.cached_input_tokens > args.input_tokens:
        parser.error("cached input tokens cannot exceed total input tokens")
    if args.calls < 1:
        parser.error("calls must be at least 1")

    manifest_path = args.shared_prefix_manifest.resolve()
    try:
        manifest = read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read shared prefix manifest: {exc}")
    if not isinstance(manifest, dict):
        parser.error("shared prefix manifest must be an object")
    prefix_path = manifest_path.parent / "shared-prefix.md"
    if not prefix_path.is_file():
        parser.error(f"shared prefix text does not exist: {prefix_path}")
    if sha256_text(prefix_path) != manifest.get("prefix_sha256"):
        parser.error("shared prefix digest does not match the manifest")

    expected = args.expected_prefix_tokens
    if expected is None:
        stored = manifest.get("expected_cached_prefix_tokens")
        expected = stored if isinstance(stored, int) and stored > 0 else None
    threshold = max(0, expected - args.tolerance_tokens) if expected is not None else None
    passed = args.cached_input_tokens >= threshold if threshold is not None else None
    verdict = (
        "pass"
        if passed is True
        else "fail"
        if passed is False
        else "observed-only"
    )
    noncached = args.input_tokens - args.cached_input_tokens
    report = {
        "schema_version": 1,
        "prefix_id": manifest.get("prefix_id"),
        "prefix_sha256": manifest.get("prefix_sha256"),
        "expected_prefix_tokens": expected,
        "tolerance_tokens": args.tolerance_tokens,
        "minimum_cached_tokens": threshold,
        "input_tokens": args.input_tokens,
        "cached_input_tokens": args.cached_input_tokens,
        "noncached_input_tokens": noncached,
        "output_tokens": args.output_tokens,
        "calls": args.calls,
        "cache_rate": (
            args.cached_input_tokens / args.input_tokens
            if args.input_tokens
            else None
        ),
        "model": args.model,
        "history_mode": args.history_mode,
        "verdict": verdict,
        "passed": passed,
        "best_effort": True,
        "note": (
            "Passing proves only that observed cached tokens reach the declared prefix "
            "boundary; the host controls actual cache routing and billing."
        ),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    output = args.output_json.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "prefix_id": report["prefix_id"],
                "verdict": verdict,
                "cache_rate": report["cache_rate"],
            },
            ensure_ascii=False,
        )
    )
    return 1 if passed is False else 0


if __name__ == "__main__":
    raise SystemExit(main())
