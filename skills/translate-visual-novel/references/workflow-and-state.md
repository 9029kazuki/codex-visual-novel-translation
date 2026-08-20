# Workflow, project layout, and state

## Directory contract

Create one project directory per game:

```text
project.json
run-state.json
source/
research/
staging/roundtrip/
staging/unpacked/
extracted/
bible/
planning/
contexts/shared-prefix/
contexts/
translations/drafts/
translations/approved/
reviews/
qa/jobs/
qa/cache/
build/
release/
```

`source/` and the original game directory are immutable inputs. Temporary unpacked resources belong under `staging`; reproducible outputs belong under `build`; distributable files alone belong under `release`.

`project.json` records schema version, title, brand, exact release, platform, source directory, `instruction_locale`, `source_locale`, and `target_locale`. Use BCP 47-style tags and do not infer a target silently.

## Stage machine

Advance `run-state.json` in order:

```text
initialized
researched
roundtrip-proven
extracted
bible-frozen
plan-approved
translating
reviewed
validated
repacked
playtested
released
```

Promote a stage only when its evidence exists. Record failures with commands, logs, affected files, and next action. Run `audit_project.py` before `set_stage.py`; do not edit the stage manually to bypass a failed gate.

## Gate evidence

### Initialization

- Exact title, release, platform, source and target locales, and source path are recorded.
- A SHA-256 source manifest exists.
- Working and output storage are adequate.

### Research

- Exact-version engine and archive evidence exists.
- `engine`, `canon`, and `target-locale` source lanes contain concrete claims.
- Canon research is multilingual; only target-language usage decisions are target-locale-specific.
- Locked decisions are traceable to evidence or an explicit coordinator decision.

### Round trip and extraction

- An untranslated extraction/reinsertion/repack round trip passed on a copy.
- Every translatable unit has stable ID, source hash, file, order, and kind.
- Controls, placeholders, voice IDs, speakers, encoding, and line endings are represented separately.
- UI, choices, narration, dialogue, system text, and image text are inventoried.

### Frozen Bible

- World rules, routes, relationships, knowledge state, character cards, voice cards, address policy, glossary, and language profile are complete enough for calibration.
- A representative scene has an approved translation.
- `bible/version.json` is incremented and frozen.

### Translation plan

- The coordinator approves semantic job boundaries and each job sets `plan_approved`.
- Every job binds the frozen source, Bible, language pair, shared prefix, decisions, and required adjacent context.
- Chunk and coverage plans give each source ID exactly one primary owner.
- Drafts pass structural validation before review.

### Release

- Approved output covers all planned IDs and automated QA has no unresolved errors.
- Font coverage and runtime rendering are evidenced for the target writing system.
- Reinsertion, repacking, startup, save/load, choices, and agreed routes pass.
- `release/` contains only intended files, instructions, checksums, and known limitations.

## Recovery

Use job states `pending`, `assigned`, `translated`, `reviewed`, `approved`, and `blocked`. Update them atomically. If an assigned job has no complete validated output after interruption, return only that job to `pending`; preserve approved jobs.

Record skill version, schema version, Bible version, source digest, shared-prefix ID/hash, decision digest, job ID, output digest, role, and validation result in machine reports. Keep timestamps, absolute paths, and mutable status out of the stable shared prompt prefix.
