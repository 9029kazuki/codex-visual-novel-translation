#!/usr/bin/env python3
"""Advance run-state.json by exactly one gate with existing evidence files."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
from audit_project import STAGES, validate_gate, validate_history, validate_project


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state_json", type=Path)
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--evidence", type=Path, action="append", required=True)
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    state_path = args.state_json.resolve()
    project_root = state_path.parent
    try:
        state: dict[str, Any] = json.loads(state_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read state: {exc}")
    current = state.get("stage")
    if current not in STAGES:
        parser.error(f"unknown current stage: {current!r}")
    current_index = STAGES.index(current)
    target_index = STAGES.index(args.stage)
    if target_index != current_index + 1:
        parser.error(
            f"stage must advance exactly one gate: current={current}, requested={args.stage}"
        )
    history_issues = validate_history(state, str(current))
    if history_issues:
        parser.error("invalid existing stage history: " + " | ".join(history_issues))
    existing_gate_issues = validate_project(project_root, str(current))
    if existing_gate_issues:
        parser.error(
            "existing project gates regressed: " + " | ".join(existing_gate_issues)
        )
    gate_issues = validate_gate(project_root, args.stage)
    if gate_issues:
        parser.error("target gate evidence is invalid: " + " | ".join(gate_issues))

    evidence: list[str] = []
    for provided in args.evidence:
        path = provided if provided.is_absolute() else project_root / provided
        path = path.resolve()
        if not path.exists():
            parser.error(f"evidence path does not exist: {path}")
        try:
            evidence.append(path.relative_to(project_root).as_posix())
        except ValueError:
            evidence.append(str(path))

    timestamp = datetime.now(timezone.utc).isoformat()
    state["stage"] = args.stage
    state["updated_at"] = timestamp
    existing_evidence = state.setdefault("evidence", [])
    for value in evidence:
        if value not in existing_evidence:
            existing_evidence.append(value)
    state.setdefault("history", []).append(
        {
            "stage": args.stage,
            "at": timestamp,
            "note": args.note,
            "evidence": evidence,
        }
    )

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=state_path.name + ".", suffix=".tmp", dir=state_path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary_name, state_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise

    print(
        json.dumps(
            {"state": str(state_path), "stage": args.stage, "evidence": evidence},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
