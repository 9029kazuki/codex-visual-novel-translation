# Translation contract

## Goal

Produce accurate, natural target-language text that can be reinserted without structural damage. Priority order:

1. Plot facts, logic, negation, modality, and time.
2. Speaker, referents, viewpoint, agent/patient roles, and character knowledge state.
3. Characterization, emotion, relationship distance, address forms, and voice.
4. Natural target-language rhythm and scene function.
5. Surface word order of the source.

Read the frozen `bible/language-profile.md` together with this contract. It defines the actual source and target locales, punctuation, register, transliteration, names, spacing, casing, line breaking, and language-specific risks.

## Structural invariants

- Output JSONL only, without Markdown or commentary inside the file.
- Emit every assigned ID exactly once and in source order; never merge or split units.
- Preserve `id`. A compact model view may omit `source_hash`, but validation and merge reconstruct it from the frozen source. If emitted, it must match exactly.
- Preserve every `protected_token` with the same content, case, count, order, and nesting.
- Preserve required newlines, escapes, placeholders, variables, voice links, ruby, waits, colors, and other controls.
- Translate only the display `text`; never alter code, resource identifiers, tag names, variables, speakers, or metadata.
- Report uncertainty in structured `issues` instead of hiding a guess in fluent prose.

## Language and narrative rules

- Translate dialogue according to the speaker’s recorded behavior and narration according to the established viewpoint and style.
- Preserve intentional ambiguity, misdirection, pauses, repetition, stuttering, interruption, and unfinished speech.
- Do not import future route knowledge into an earlier line or resolve a mystery before the source does.
- Check omitted subjects, pronouns, gender, number, agreement, tense, aspect, modality, passive/causative structures, conditionals, questions, and idioms according to the source profile.
- Do not invent pronouns, relationships, profanity, memes, dialect, or explanatory detail without source and context support.
- Follow locked names, terminology, address forms, and forbidden variants. Handle wordplay, nicknames, sound symbolism, and cultural references by scene function and report proposals when a global decision is needed.
- Follow target-locale punctuation and typography while respecting engine and text-box constraints.

## Shared and job context

The clean shared prefix contains this contract, the language profile, world rules, all character and voice records, address policy, complete glossary, route knowledge, approved examples, and the current frozen decisions. Keep it stable across a cohort.

Append the job contract, complete current scene, route/time/location state, required preceding context, and clearly marked non-leakable future context afterward. For a chunked scene, process `chunk-plan.json` in natural order, emit only primary IDs, and use overlap solely for understanding.

## Output schema

```json
{"id":"route01.ks:000042","translation":"...","confidence":"high","issues":[],"term_proposals":[]}
```

`confidence` is `high`, `medium`, or `low`. Example issue:

```json
{"type":"ambiguous-subject","message":"The actor may be the protagonist or Misaki; verify the preceding animation cue."}
```

Example terminology proposal:

```json
{"source":"御三家","proposal":"Three Great Houses","scope":"global","reason":"The scene explicitly identifies three founding families.","evidence_ids":["..."]}
```

Delegated agents may propose terminology but never edit the global glossary. Before delivery, silently check completeness, semantic roles, negation, voice, spoiler state, controls, residual source text, and likely text-box fit. Then write only the requested JSONL and a concise handoff.
