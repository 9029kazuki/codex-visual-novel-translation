#!/usr/bin/env python3
"""Audit visible localization text against the cmap of release fonts.

This is a static gate only.  It proves that the selected font files contain
the requested code points; it cannot prove that a game loads or selects those
fonts at runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


NAME_IDS = {
    1: "family",
    2: "subfamily",
    4: "full_name",
    6: "postscript_name",
}


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def decode_file(path: Path, encoding: str | None) -> str:
    data = path.read_bytes()
    if encoding:
        return data.decode(encoding)
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


def sfnt_face_offsets(data: bytes, path: Path) -> list[int]:
    if data[:4] != b"ttcf":
        if len(data) < 12:
            raise RuntimeError(f"{path}: truncated SFNT header")
        return [0]
    if len(data) < 12:
        raise RuntimeError(f"{path}: truncated TTC header")
    count = u32(data, 8)
    if count < 1 or count > 4096 or 12 + 4 * count > len(data):
        raise RuntimeError(f"{path}: invalid TTC face directory")
    offsets = [u32(data, 12 + 4 * index) for index in range(count)]
    if any(offset + 12 > len(data) for offset in offsets):
        raise RuntimeError(f"{path}: TTC face offset is outside the file")
    return offsets


def find_table(
    data: bytes,
    sfnt_offset: int,
    tag_wanted: bytes,
    path: Path,
) -> tuple[int, int] | None:
    if sfnt_offset + 12 > len(data):
        raise RuntimeError(f"{path}: truncated SFNT offset table")
    table_count = u16(data, sfnt_offset + 4)
    directory = sfnt_offset + 12
    if directory + 16 * table_count > len(data):
        raise RuntimeError(f"{path}: truncated SFNT table directory")
    for index in range(table_count):
        record = directory + 16 * index
        tag = data[record : record + 4]
        offset = u32(data, record + 8)
        length = u32(data, record + 12)
        if tag != tag_wanted:
            continue
        if offset > len(data) or length > len(data) - offset:
            raise RuntimeError(f"{path}: {tag_wanted!r} table is truncated")
        return offset, length
    return None


def cmap_format_4(data: bytes, base: int, table_end: int) -> set[int]:
    if base + 16 > table_end:
        return set()
    length = u16(data, base + 2)
    end = min(table_end, base + length)
    seg_count = u16(data, base + 6) // 2
    end_codes = base + 14
    start_codes = end_codes + 2 * seg_count + 2
    deltas = start_codes + 2 * seg_count
    ranges = deltas + 2 * seg_count
    if ranges + 2 * seg_count > end:
        return set()
    result: set[int] = set()
    for index in range(seg_count):
        start = u16(data, start_codes + 2 * index)
        stop = u16(data, end_codes + 2 * index)
        delta = u16(data, deltas + 2 * index)
        range_offset_pos = ranges + 2 * index
        range_offset = u16(data, range_offset_pos)
        if start > stop:
            continue
        for codepoint in range(start, stop + 1):
            if codepoint == 0xFFFF:
                continue
            if range_offset == 0:
                glyph = (codepoint + delta) & 0xFFFF
            else:
                glyph_pos = range_offset_pos + range_offset + 2 * (codepoint - start)
                if glyph_pos + 2 > end:
                    continue
                glyph = u16(data, glyph_pos)
                if glyph:
                    glyph = (glyph + delta) & 0xFFFF
            if glyph:
                result.add(codepoint)
    return result


def cmap_format_12_or_13(
    data: bytes,
    base: int,
    table_end: int,
    constant: bool,
) -> set[int]:
    if base + 16 > table_end:
        return set()
    length = u32(data, base + 4)
    end = min(table_end, base + length)
    groups = u32(data, base + 12)
    cursor = base + 16
    result: set[int] = set()
    for _ in range(groups):
        if cursor + 12 > end:
            break
        start, stop, glyph = struct.unpack_from(">III", data, cursor)
        cursor += 12
        if start > stop or start > 0x10FFFF:
            continue
        stop = min(stop, 0x10FFFF)
        if constant:
            if glyph:
                result.update(range(start, stop + 1))
        else:
            first = start + 1 if glyph == 0 else start
            if first <= stop:
                result.update(range(first, stop + 1))
    return result


def read_unicode_cmap(
    data: bytes,
    sfnt_offset: int,
    path: Path,
) -> set[int]:
    table = find_table(data, sfnt_offset, b"cmap", path)
    if table is None:
        raise RuntimeError(f"{path}: cmap table not found")
    cmap_offset, cmap_length = table
    cmap_end = cmap_offset + cmap_length
    if cmap_offset + 4 > cmap_end:
        raise RuntimeError(f"{path}: truncated cmap header")
    encoding_count = u16(data, cmap_offset + 2)
    supported: set[int] = set()
    seen_offsets: set[int] = set()
    for index in range(encoding_count):
        record = cmap_offset + 4 + 8 * index
        if record + 8 > cmap_end:
            break
        platform, encoding = struct.unpack_from(">HH", data, record)
        relative = u32(data, record + 4)
        base = cmap_offset + relative
        if base in seen_offsets or base + 2 > cmap_end:
            continue
        if platform != 0 and not (platform == 3 and encoding in {1, 10}):
            continue
        seen_offsets.add(base)
        fmt = u16(data, base)
        if fmt == 4:
            supported.update(cmap_format_4(data, base, cmap_end))
        elif fmt == 12:
            supported.update(cmap_format_12_or_13(data, base, cmap_end, constant=False))
        elif fmt == 13:
            supported.update(cmap_format_12_or_13(data, base, cmap_end, constant=True))
    if not supported:
        raise RuntimeError(f"{path}: no supported Unicode cmap subtable")
    return supported


def decode_name(platform: int, raw: bytes) -> str | None:
    try:
        if platform in {0, 3}:
            value = raw.decode("utf-16-be")
        elif platform == 1:
            value = raw.decode("mac_roman")
        else:
            return None
    except UnicodeDecodeError:
        return None
    value = " ".join(value.replace("\x00", "").split())
    return value or None


def read_font_names(
    data: bytes,
    sfnt_offset: int,
    path: Path,
) -> dict[str, str]:
    table = find_table(data, sfnt_offset, b"name", path)
    if table is None:
        return {}
    table_offset, table_length = table
    table_end = table_offset + table_length
    if table_offset + 6 > table_end:
        return {}
    count = u16(data, table_offset + 2)
    strings = table_offset + u16(data, table_offset + 4)
    records = table_offset + 6
    selected: dict[int, tuple[int, str]] = {}
    for index in range(count):
        record = records + 12 * index
        if record + 12 > table_end:
            break
        platform, _encoding, language, name_id, length, relative = struct.unpack_from(
            ">HHHHHH", data, record
        )
        if name_id not in NAME_IDS:
            continue
        start = strings + relative
        stop = start + length
        if start < table_offset or stop > table_end:
            continue
        value = decode_name(platform, data[start:stop])
        if not value:
            continue
        if platform == 3 and language == 0x0409:
            rank = 0
        elif platform == 0:
            rank = 1
        elif platform == 3:
            rank = 2
        else:
            rank = 3
        if name_id not in selected or rank < selected[name_id][0]:
            selected[name_id] = (rank, value)
    return {
        NAME_IDS[name_id]: ranked[1]
        for name_id, ranked in sorted(selected.items())
    }


def parse_font_spec(spec: str) -> tuple[Path, int]:
    if "::" not in spec:
        return Path(spec).expanduser().resolve(), 0
    path_text, face_text = spec.rsplit("::", 1)
    try:
        face_index = int(face_text)
    except ValueError as exc:
        raise RuntimeError(f"invalid font face index in {spec!r}") from exc
    if face_index < 0:
        raise RuntimeError(f"font face index must not be negative: {spec!r}")
    return Path(path_text).expanduser().resolve(), face_index


def inspect_font(spec: str) -> tuple[dict[str, Any], set[int]]:
    path, face_index = parse_font_spec(spec)
    if not path.is_file():
        raise RuntimeError(f"font does not exist: {path}")
    data = path.read_bytes()
    offsets = sfnt_face_offsets(data, path)
    if face_index >= len(offsets):
        raise RuntimeError(
            f"{path}: face index {face_index} is out of range for {len(offsets)} faces"
        )
    sfnt_offset = offsets[face_index]
    cmap = read_unicode_cmap(data, sfnt_offset, path)
    record = {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "collection_faces": len(offsets),
        "face_index": face_index,
        "names": read_font_names(data, sfnt_offset, path),
        "unicode_cmap_codepoints": len(cmap),
    }
    return record, cmap


def read_jsonl(path: Path, encoding: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(decode_file(path, encoding).splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"{path}:{line_number}: expected a JSON object")
        value = dict(value)
        value["__audit_line__"] = line_number
        rows.append(value)
    return rows


def source_token_map(path: Path | None, encoding: str | None) -> dict[str, list[str]]:
    if path is None:
        return {}
    result: dict[str, list[str]] = {}
    for row in read_jsonl(path.resolve(), encoding):
        entry_id = row.get("id")
        tokens = row.get("protected_tokens") or []
        if not isinstance(entry_id, str) or not entry_id:
            continue
        if not isinstance(tokens, list) or any(not isinstance(token, str) for token in tokens):
            raise RuntimeError(f"{path}: {entry_id}: protected_tokens is not a string list")
        result[entry_id] = tokens
    return result


def strip_exact_tokens(text: str, tokens: Iterable[str]) -> str:
    remaining = text
    for token in tokens:
        remaining = remaining.replace(token, "", 1)
    return remaining


def visible_codepoint(character: str) -> bool:
    return not character.isspace() and not unicodedata.category(character).startswith("C")


def add_text(
    text: str,
    location: str,
    counts: Counter[int],
    examples: dict[int, list[str]],
) -> None:
    for character in text:
        if not visible_codepoint(character):
            continue
        codepoint = ord(character)
        counts[codepoint] += 1
        if len(examples[codepoint]) < 5 and location not in examples[codepoint]:
            examples[codepoint].append(location)


def selected_strings(value: Any) -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield "", value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, str):
                yield f"[{index}]", item


def collect_selected_fields(
    value: Any,
    fields: set[str],
    tokens_by_id: dict[str, list[str]],
    keep_protected_tokens: bool,
    location: str,
    counts: Counter[int],
    examples: dict[int, list[str]],
    inherited_id: str | None = None,
    inherited_tokens: list[str] | None = None,
) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            collect_selected_fields(
                item,
                fields,
                tokens_by_id,
                keep_protected_tokens,
                f"{location}[{index}]",
                counts,
                examples,
                inherited_id,
                inherited_tokens,
            )
        return
    if not isinstance(value, dict):
        return

    entry_id = value.get("id") if isinstance(value.get("id"), str) else inherited_id
    raw_tokens = value.get("protected_tokens")
    if isinstance(raw_tokens, list) and all(isinstance(token, str) for token in raw_tokens):
        tokens = list(raw_tokens)
    elif entry_id and entry_id in tokens_by_id:
        tokens = tokens_by_id[entry_id]
    else:
        tokens = inherited_tokens or []
    if entry_id:
        record_location = f"{location}#{entry_id}"
    elif "__audit_line__" in value:
        record_location = f"{location}:{value['__audit_line__']}"
    else:
        record_location = location

    for key, child in value.items():
        child_location = f"{record_location}.{key}"
        if key in fields:
            for suffix, text in selected_strings(child):
                visible = text if keep_protected_tokens else strip_exact_tokens(text, tokens)
                add_text(visible, child_location + suffix, counts, examples)
        if isinstance(child, (dict, list)):
            collect_selected_fields(
                child,
                fields,
                tokens_by_id,
                keep_protected_tokens,
                child_location,
                counts,
                examples,
                entry_id,
                tokens,
            )


def collect_input(
    path: Path,
    fields: set[str],
    tokens_by_id: dict[str, list[str]],
    keep_protected_tokens: bool,
    encoding: str | None,
    counts: Counter[int],
    examples: dict[int, list[str]],
) -> None:
    path = path.resolve()
    if not path.is_file():
        raise RuntimeError(f"input does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        for row in read_jsonl(path, encoding):
            collect_selected_fields(
                row,
                fields,
                tokens_by_id,
                keep_protected_tokens,
                str(path),
                counts,
                examples,
            )
    elif suffix == ".json":
        try:
            value = json.loads(decode_file(path, encoding))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{path}: invalid JSON: {exc}") from exc
        collect_selected_fields(
            value,
            fields,
            tokens_by_id,
            keep_protected_tokens,
            str(path),
            counts,
            examples,
        )
    else:
        add_text(decode_file(path, encoding), str(path), counts, examples)


def missing_item(
    codepoint: int,
    counts: Counter[int],
    examples: dict[int, list[str]],
) -> dict[str, Any]:
    character = chr(codepoint)
    return {
        "character": character,
        "codepoint": f"U+{codepoint:04X}",
        "unicode_name": unicodedata.name(character, "<unassigned>"),
        "occurrences": counts.get(codepoint, 0),
        "examples": examples.get(codepoint, []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument(
        "--field",
        action="append",
        help="JSON/JSONL string field to scan; repeat as needed (default: translation)",
    )
    parser.add_argument(
        "--source-jsonl",
        type=Path,
        help="Optional frozen source used to remove exact protected_tokens by id",
    )
    parser.add_argument(
        "--font",
        action="append",
        required=True,
        help="Release font path; append ::FACE_INDEX for TTC files",
    )
    parser.add_argument("--license", action="append", type=Path, default=[])
    parser.add_argument("--require-license", action="store_true")
    parser.add_argument("--probe", default="")
    parser.add_argument("--encoding")
    parser.add_argument("--keep-protected-tokens", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    errors: list[str] = []
    fields = set(args.field or ["translation"])
    try:
        tokens_by_id = source_token_map(args.source_jsonl, args.encoding)
    except (OSError, RuntimeError, UnicodeError) as exc:
        errors.append(str(exc))
        tokens_by_id = {}

    counts: Counter[int] = Counter()
    examples: dict[int, list[str]] = defaultdict(list)
    for input_path in args.input:
        try:
            collect_input(
                input_path,
                fields,
                tokens_by_id,
                args.keep_protected_tokens,
                args.encoding,
                counts,
                examples,
            )
        except (OSError, RuntimeError, UnicodeError) as exc:
            errors.append(str(exc))

    fonts: list[dict[str, Any]] = []
    combined_cmap: set[int] = set()
    for spec in args.font:
        try:
            record, cmap = inspect_font(spec)
            fonts.append(record)
            combined_cmap.update(cmap)
        except (OSError, RuntimeError, struct.error) as exc:
            errors.append(str(exc))

    licenses: list[dict[str, Any]] = []
    for license_path in args.license:
        path = license_path.expanduser().resolve()
        if not path.is_file():
            errors.append(f"license does not exist: {path}")
            continue
        licenses.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    if args.require_license and not licenses:
        errors.append("--require-license was set but no valid license file was supplied")
    if not counts:
        errors.append("no visible characters were collected from the selected inputs and fields")
    if not combined_cmap:
        errors.append("no usable Unicode cmap was loaded")

    used = set(counts)
    missing = sorted(used - combined_cmap)
    probe_codepoints = {
        ord(character) for character in args.probe if visible_codepoint(character)
    }
    missing_probes = sorted(probe_codepoints - combined_cmap)
    passed = not errors and not missing and not missing_probes
    report = {
        "schema_version": 1,
        "passed": passed,
        "static_only": True,
        "runtime_tested": False,
        "runtime_test_reason": (
            "A cmap audit cannot prove that the game loads or selects these fonts."
        ),
        "inputs": [str(path.expanduser().resolve()) for path in args.input],
        "source_jsonl": (
            str(args.source_jsonl.expanduser().resolve())
            if args.source_jsonl
            else None
        ),
        "text_fields": sorted(fields),
        "protected_tokens_removed": not args.keep_protected_tokens,
        "fonts": fonts,
        "font_union_codepoints": len(combined_cmap),
        "license_files": licenses,
        "license_required": args.require_license,
        "visible_character_occurrences": sum(counts.values()),
        "distinct_visible_codepoints": len(used),
        "covered_codepoints": len(used - set(missing)),
        "missing_count": len(missing),
        "missing": [missing_item(codepoint, counts, examples) for codepoint in missing],
        "probe": {
            chr(codepoint): codepoint in combined_cmap
            for codepoint in sorted(probe_codepoints)
        },
        "missing_probe_count": len(missing_probes),
        "missing_probes": [
            missing_item(codepoint, counts, examples) for codepoint in missing_probes
        ],
        "errors": errors,
    }
    report_path = args.report.expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "distinct_visible_codepoints": report["distinct_visible_codepoints"],
                "missing_count": report["missing_count"],
                "missing_probe_count": report["missing_probe_count"],
                "errors": len(errors),
                "report": str(report_path),
            },
            ensure_ascii=False,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
