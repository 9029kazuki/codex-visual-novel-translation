# Delegated-agent orchestration

## Roles

The coordinator owns project state, research synthesis, extraction, job approval, terminology decisions, merges, repacking, and delivery.

Bounded roles may include:

- engine and archive researcher;
- canon and character-voice researcher;
- target-locale terminology researcher;
- calibration translator and reviewer;
- scene translator;
- independent scene reviewer;
- UI and ancillary-text translator;
- packaging or runtime-font investigator.

Do not delegate the whole project to one agent. Do not let multiple agents write the same file.

## Research delegation

Research agents write separate notes and source records. The coordinator reads their evidence, resolves conflicts, and materializes the shared Bible. Agents may propose names or terminology but never directly freeze global decisions.

The engine lane should identify exact versions, signatures, successful commands, encodings, signing/encryption, and repacking limits. The canon lane should prioritize in-game and official evidence in any language. The target-locale lane should focus on established localized names, terminology, style, and audience expectations.

## Translation jobs

Prefer one complete scene or tightly connected scene group per job. Merge tiny sequential files and split very large scenes at semantic boundaries. Bind every job to:

- source IDs and source digest;
- Bible version and shared-prefix ID/hash;
- decision snapshot digest;
- route, time, location, preceding state, and adjacent context;
- source and target locales;
- exclusive draft and QA paths.

Use a clean prefix seed for a cohort when possible. A translation agent reads the complete scene, follows `chunk-plan.json`, emits each primary ID once, preserves protected tokens, and writes only its assigned draft and handoff.

## Independent review

The reviewer reads the frozen contract, language profile, Bible, latest decisions, complete source context, and draft. It checks meaning, semantic roles, negation, modality, chronology, knowledge state, voice, address, terminology, natural target language, controls, and layout risk.

Prefer a sparse review delta containing only revisions plus a coverage declaration and draft digest. Approved entries remain byte-identical to the draft; revised entries contain complete replacement translations and reasons. The coordinator validates the delta with `apply_review_delta.py` before materializing approved output.

## Capacity and recovery

Dispatch in cohorts and retain capacity for coordination and review. Validate the first returned job before scaling up. Collect and validate jobs continuously instead of waiting for all translation to finish.

Agents write only their own output paths. If an agent stops without a complete validated artifact, return that job to `pending`; do not redo approved jobs. When agent support is unavailable, the coordinator executes the same contracts sequentially and records the fallback.

## Prompt skeletons

Clean seed:

```text
Use $translate-visual-novel as the clean seed for formal translation jobs.
Read the shared-prefix manifest and every section in manifest order.
Verify the prefix hash, then wait for bounded jobs.
```

Translator:

```text
Translate only the assigned job using the inherited shared prefix.
Read the complete scene and chunk plan. Emit every primary ID exactly once,
preserve protected tokens, validate the JSONL, and write only the assigned files.
```

Reviewer:

```text
Independently review the assigned draft against the complete source scene,
language profile, Bible, and frozen decisions. Write only the requested sparse
review delta and coverage declaration.
```
