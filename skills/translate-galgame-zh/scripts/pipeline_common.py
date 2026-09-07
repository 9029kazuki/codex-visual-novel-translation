"""Deterministic snapshots, semantic dependencies, and local planning budgets."""
from __future__ import annotations

import contextlib
import contextvars
import csv
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any

REVISION = 3
_CACHE = contextvars.ContextVar("localization_read_snapshot", default=None)
PROVENANCE_FIELDS = {"source_url", "source_urls", "sources", "retrieved_at", "updated_at", "generated_at", "created_at", "source_language", "authority", "provenance", "schema_version"}


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def digest_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest_value(value: Any) -> str:
    return digest_text(json_text(value))


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_text(path: Path) -> str:
    path = path.resolve()
    cache = _CACHE.get()
    if cache is not None:
        if path not in cache["bytes"]:
            cache["bytes"][path] = path.read_bytes()
            cache["physical_reads"] += 1
            cache["file_cache_misses"] += 1
        data = cache["bytes"][path]
    else:
        data = path.read_bytes()
    return data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")


def read_json(path: Path) -> Any:
    cache = _CACHE.get()
    key = (path.resolve(), "json")
    if cache is not None and key in cache["parsed"]:
        return cache["parsed"][key]
    result = json.loads(read_text(path))
    if cache is not None:
        cache["parsed"][key] = result
    return result


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    cache = _CACHE.get()
    key = (path.resolve(), "jsonl")
    if cache is not None and key in cache["parsed"]:
        return cache["parsed"][key]
    rows = []
    for number, line in enumerate(read_text(path).splitlines(), 1):
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{number}: expected object")
            rows.append(value)
    if cache is not None:
        cache["parsed"][key] = rows
        cache["parsed_jsonl_records"] += len(rows)
    return rows


@contextlib.contextmanager
def read_snapshot():
    """Reuse reads only inside one batch, and reject input changes before return."""
    cache = {"bytes": {}, "parsed": {}, "physical_reads": 0, "file_cache_misses": 0, "verification_reads": 0, "parsed_jsonl_records": 0}
    token = _CACHE.set(cache)
    try:
        yield cache
        for path, data in cache["bytes"].items():
            cache["physical_reads"] += 1
            cache["verification_reads"] += 1
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError(f"input changed during batch; rebuild affected bundles: {path}")
    finally:
        _CACHE.reset(token)


def semantic(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: semantic(child) for key, child in value.items() if key not in PROVENANCE_FIELDS and not key.startswith("_audit")}
    if isinstance(value, list):
        return [semantic(child) for child in value]
    return value


def decisions_view(value: Any) -> Any:
    if isinstance(value, dict):
        value = {key: child for key, child in value.items() if key not in {"pending", "proposed", "history"}}
    if isinstance(value, list):
        value = [child for child in value if not isinstance(child, dict) or child.get("status") not in {"pending", "proposed", "rejected"}]
    return semantic(value)


def load_semantics(project: Path, contract: Path | None = None, decisions: Path | None = None) -> dict[str, Any]:
    contract = contract or Path(__file__).resolve().parent.parent / "references/translation-contract.md"
    if decisions is None:
        decisions = project / "planning/translation-decisions.json"
        if not decisions.is_file():
            decisions = project / "research/decisions.md"
    if decisions.suffix.lower() == ".json":
        decision_data = decisions_view(read_json(decisions))
    elif decisions.suffix.lower() == ".jsonl":
        decision_data = decisions_view(read_jsonl(decisions))
    else:
        decision_data = read_text(decisions).rstrip() + "\n"
    glossary = list(csv.DictReader(io.StringIO(read_text(project / "bible/glossary.tsv")), delimiter="\t"))
    glossary = [semantic(row) for row in glossary if row.get("status") != "proposed"]
    glossary.sort(key=lambda row: (row.get("scope", ""), row.get("source", ""), row.get("target", ""), row.get("status", "")))
    characters = semantic(read_json(project / "bible/characters.json"))
    if isinstance(characters, dict) and isinstance(characters.get("characters"), list):
        characters["characters"].sort(key=lambda item: str(item.get("id") or item.get("name") or item.get("jp_name") or ""))
    return {
        "contract": read_text(contract).rstrip() + "\n",
        "world": read_text(project / "bible/world.md").rstrip() + "\n",
        "characters": characters,
        "voice": semantic(read_json(project / "bible/voice.json")),
        "honorifics": read_text(project / "bible/honorifics.md").rstrip() + "\n",
        "glossary": glossary,
        "knowledge": semantic(read_json(project / "bible/route-knowledge.json")),
        "calibration": semantic(read_jsonl(project / "bible/calibration.jsonl")),
        "decisions": decision_data,
    }


def names(character: dict[str, Any]) -> set[str]:
    values = {str(character[key]) for key in ("id", "name", "jp_name", "source_name", "zh_name", "target_name") if character.get(key)}
    values.update(str(item) for item in character.get("aliases", []) if item)
    return values


def scoped_semantics(data: dict[str, Any], scope: dict[str, Any] | None) -> dict[str, Any]:
    """A coordinator-approved dependency closure; full project is the safe default."""
    if not scope or scope.get("mode", "project") == "project":
        return data
    if scope.get("mode") != "selected" or scope.get("approved") is not True or not str(scope.get("rationale") or "").strip():
        raise ValueError("selected dependency scope needs approved=true and a rationale")
    for key in ("characters", "routes"):
        if not isinstance(scope.get(key), list) or any(not isinstance(x, str) or not x for x in scope[key]):
            raise ValueError(f"dependency scope {key} must be a string array")
    result = dict(data)
    requested = set(scope["characters"])
    characters = data["characters"].get("characters", [])
    selected = [item for item in characters if names(item) & requested]
    found = set().union(*(names(item) for item in selected)) if selected else set()
    if requested - found:
        raise ValueError(f"unknown dependency characters: {sorted(requested - found)}")
    result["characters"] = {**data["characters"], "characters": selected}
    voice = data["voice"]
    result["voice"] = {**voice, "characters": {key: value for key, value in voice.get("characters", {}).items() if key in found}}
    knowledge = data["knowledge"]
    routes = set(scope["routes"]) | {"common"}
    unknown = set(scope["routes"]) - set(knowledge.get("routes", {}))
    if unknown:
        raise ValueError(f"unknown dependency routes: {sorted(unknown)}")
    result["knowledge"] = {**knowledge, "routes": {key: value for key, value in knowledge.get("routes", {}).items() if key in routes}}
    # Global terms and all accepted decisions remain required. Explicit extras
    # cover scene/era/speaker scopes that cannot be inferred from route names.
    allowed = {"", "global", *routes, *found, *scope.get("extra_scopes", [])}
    result["glossary"] = [row for row in data["glossary"] if row.get("scope", "global") in allowed]
    result["calibration"] = [item for item in data["calibration"] if not item.get("speaker") or item.get("speaker") in found]
    return result


def inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    candidate.relative_to(root.resolve())
    return candidate


def load_prefix(path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    manifest = read_json(path)
    if not isinstance(manifest, dict):
        raise ValueError("prefix manifest must be an object")
    text = read_text(path.parent / "shared-prefix.md")
    if digest_text(text) != manifest.get("prefix_sha256"):
        raise ValueError("shared prefix digest mismatch")
    sections = manifest.get("sections", [])
    if not sections:
        raise ValueError("prefix has no sections")
    section_text = []
    for item in sections:
        value = read_text(inside(path.parent, item["file"]))
        if digest_text(value) != item.get("sha256"):
            raise ValueError(f"prefix section digest mismatch: {item['file']}")
        section_text.append(value.rstrip("\n"))
    if "\n".join(section_text) + "\n" != text:
        raise ValueError("prefix text does not match ordered sections")
    semantic_data = None
    if manifest.get("semantic_inputs"):
        item = manifest["semantic_inputs"]
        semantic_data = read_json(inside(path.parent, item["file"]))
        if digest_value(semantic_data) != item.get("sha256"):
            raise ValueError("semantic inputs digest mismatch")
    return manifest, semantic_data


class TokenCounter:
    def __init__(self, encoding: str | None = None):
        self.encoding = encoding
        self.encode = None
        if encoding:
            try:
                import tiktoken
                self.encode = tiktoken.get_encoding(encoding).encode
            except (ImportError, ValueError) as exc:
                raise ValueError("requested tokenizer unavailable; install tiktoken or omit --encoding") from exc

    @property
    def method(self) -> str:
        return f"tiktoken:{self.encoding}:proxy" if self.encode else "utf8-bytes:conservative-planning-estimate"

    def count(self, text: str) -> int:
        return len(self.encode(text, disallowed_special=())) if self.encode else len(text.encode("utf-8"))


def bundle_dir(project: Path, job_id: str) -> Path:
    root = inside(project / "contexts", job_id)
    pointer = root / "current.json"
    if pointer.is_file():
        payload = read_json(pointer)
        destination = inside(root, payload["snapshot"])
        if digest_text(read_text(destination / "bundle-status.json")) != payload.get("status_sha256"):
            raise ValueError("bundle pointer/status digest mismatch")
        return destination
    return root  # Read-only compatibility with legacy bundles.


def job_contract_digest(job):
    keys = ("route", "scene_ids", "time", "location", "prior_summary", "context_notes", "predecessors", "adjacent_entry_ids", "dependency_scope")
    return digest_value({key: job.get(key) for key in keys})


def validate_bundle(project: Path, job: dict[str, Any], current_semantics: dict[str, Any] | None = None) -> list[str]:
    try:
        root = bundle_dir(project, job["job_id"])
        status = read_json(root / "bundle-status.json")
        if status.get("valid") is not True or status.get("source_digest") != job.get("source_digest"):
            raise ValueError("bundle is invalid or source digest is stale")
        if status.get("schema_version", 0) < 3:
            raise ValueError("legacy bundle needs an explicit v3 rebuild before dispatch")
        if status.get("job_contract_digest") != job_contract_digest(job):
            raise ValueError("job boundary/context/dependency contract changed")
        source_by_id = {row["id"]: row for row in read_jsonl(project / "extracted/source.jsonl")}
        selected = set(job["entry_ids"])
        scene = [source_by_id[x] for x in job["entry_ids"]]
        adjacent = [source_by_id[x] for x in dict.fromkeys(job.get("adjacent_entry_ids", [])) if x not in selected]
        if digest_value({"scene": scene, "adjacent": adjacent}) != status.get("input_records_digest"):
            raise ValueError("source or adjacent record contents changed")
        for relative, expected in status["artifacts"].items():
            if digest_text(read_text(inside(root, relative))) != expected:
                raise ValueError(f"artifact digest mismatch: {relative}")
        plan = read_json(root / "chunk-plan.json")
        coverage = read_json(root / "coverage-plan.json")
        primary = [entry for chunk in plan["chunks"] for entry in chunk["primary_entry_ids"]]
        if primary != job["entry_ids"] or len(primary) != len(set(primary)):
            raise ValueError("primary coverage/order differs from job")
        if coverage.get("assignments") != {entry: chunk["chunk_id"] for chunk in plan["chunks"] for entry in chunk["primary_entry_ids"]}:
            raise ValueError("coverage assignments differ from chunk plan")
        for chunk in plan["chunks"]:
            for field, ids in (("primary_source", "primary_entry_ids"), ("overlap_before_source", "overlap_before_ids"), ("overlap_after_source", "overlap_after_ids")):
                if [row["id"] for row in read_jsonl(inside(root, chunk[field]))] != chunk[ids]:
                    raise ValueError(f"chunk file IDs differ: {chunk[field]}")
        if not status.get("budget", {}).get("planning_passed"):
            raise ValueError("bundle has no passing planning budget")
        manifest_path = Path(status["shared_prefix_manifest"])
        if not manifest_path.is_absolute():
            manifest_path = project / manifest_path
        manifest, frozen = load_prefix(manifest_path)
        if manifest["prefix_sha256"] != status["shared_prefix_sha256"] or manifest["prefix_id"] != status["shared_prefix_id"]:
            raise ValueError("bundle prefix binding differs")
        if frozen is None:
            raise ValueError("prefix lacks semantic dependency snapshot")
        scope = status.get("dependency_scope")
        if digest_value(scoped_semantics(frozen, scope)) != status["dependency_digest"]:
            raise ValueError("frozen dependency digest differs")
        contract = Path(manifest["contract_source"])
        decisions = Path(manifest.get("live_decisions_source") or manifest["decision_snapshot"]["source"])
        if not decisions.is_absolute():
            decisions = project / decisions
        live = current_semantics or load_semantics(project, contract, decisions)
        if digest_value(scoped_semantics(live, scope)) != status["dependency_digest"]:
            raise ValueError("semantic dependencies changed; targeted review/rebuild required")
        return []
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return [f"job {job.get('job_id')}: {exc}"]
