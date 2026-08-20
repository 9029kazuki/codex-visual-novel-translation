# Extraction, reinsertion, and repacking

## Research before operating

Before using an unpacker, record the exact game version, visible extensions, file signatures, suspected engine, successful reports, tool versions, encodings, encryption or signing, and known repacking limits.

Opening an archive is not proof that it can be rebuilt losslessly. Prove the entire round trip before committing to full translation.

## Optional GARbro use

This skill does not redistribute GARbro. Provide a user-installed copy through `-Path`, `GARBRO_PATH`, or the system `PATH`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/locate_garbro.ps1 -Path C:\Tools\GARbro
```

Use `-Launch` only when visible GUI work is wanted. Test one small archive before processing the complete game. If GARbro fails, inspect signatures again and research a version-specific extractor and rebuilder.

## Untranslated round trip

1. Copy the smallest representative archive into `staging/roundtrip/input`.
2. Extract it into `staging/roundtrip/unpacked`.
3. Change no text and rebuild into `staging/roundtrip/repacked`.
4. Compare file counts, relative paths, unpacked hashes, metadata, and archive listings.
5. Test the rebuilt copy in the game when launch permission exists.
6. Record exact commands, versions, results, and differences in `research/unpack-notes.md`.

If the round trip fails, continue research but do not claim that a complete patch can be delivered.

## Lossless text model

Represent each translatable unit as one JSONL object:

```json
{"id":"route01.ks:000042","source_hash":"sha256:...","file":"scenario/route01.ks","order":42,"route":"route01","scene_id":"route01-rooftop","kind":"dialogue","speaker":"Misaki","voice_id":"v_00123","text":"……そうなんだ。","protected_tokens":["[wait]"],"boundary_before":false,"metadata":{}}
```

Requirements:

- IDs are stable and unique for the frozen source release.
- The source hash covers exact source text and any structural fields needed for safe reinsertion.
- `text` contains only display text selected for translation.
- `protected_tokens` preserves tags, placeholders, variables, escapes, and engine controls in occurrence order.
- Keep speakers, voice IDs, tags, routes, file positions, encodings, BOM state, newline style, and terminal newline metadata.

Do not blindly protect every bracketed string. Some engines store translatable text inside tag parameters; use an engine-aware parser first.

## Scene graph and reinsertion

Build `extracted/script-map.json` from labels, jumps, calls, returns, choices, route variables, audiovisual transitions, dates, locations, and viewpoint changes. Use semantic scene boundaries before file boundaries when planning jobs.

Reinsert only by stable ID after verifying the frozen source hash. Preserve the proven encoding or use a deliberately tested replacement. Build into a new `build/<build-id>` directory, keep commands and logs, read the rebuilt container back, and generate the release only from a verified build.

When a new font is required, read [font-runtime.md](font-runtime.md), use a redistributable font, and record its file hash, internal face names, license, and archive path.
