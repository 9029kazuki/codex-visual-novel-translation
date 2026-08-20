# QA, playtesting, and release

## Per-job automated checks

Run `validate_translation.py` after every draft and again after review materialization. Treat these as errors:

- missing, duplicate, extra, or reordered IDs;
- mismatched source hashes when provided;
- missing, duplicated, reordered, or altered protected tokens;
- changed required newline counts;
- empty translations, NUL, or replacement characters;
- locked terminology violations;
- invalid structured fields.

Warnings require adjudication rather than blind suppression:

- source text left unchanged;
- residual source-script characters according to the locale profile;
- unusual language-pair length ratio;
- repeated source translated inconsistently;
- preferred terminology not used;
- low confidence or unresolved issues.

## Independent semantic review

Review the complete scene, not isolated lines. Check omitted subjects, agent/patient roles, negation, causative and passive meaning, tense/aspect, deixis, pronouns, relationship distance, character knowledge, route state, jokes, wordplay, and target-language naturalness.

Do not “improve” intentional ambiguity or add explanations from later scenes. Verify that every revision preserves controls and returns a complete replacement string.

## Global QA

After all jobs are approved, merge deterministically and check:

- complete planned ID coverage;
- glossary and name consistency across jobs;
- duplicate-source decisions and intentional contextual variants;
- UI, choices, narration, dialogue, system strings, image text, and save titles;
- forbidden forms and unresolved proposals;
- encoding, Unicode normalization, line endings, and text-box limits;
- target-script font coverage and runtime selection.

Use locale-specific checks for casing, quotation, spacing, punctuation, plural/gender agreement, diacritics, bidirectional text, shaping, and line breaking as applicable.

## Repack and playtest

Reinsert by stable ID only after verifying source hashes. Rebuild into a new build directory, inspect the produced archive, compare expected patch contents, and test a game copy.

Exercise startup, new game, existing save where relevant, save/load, backlog, choices, skip/auto, settings, names, UI, route transitions, and endings within the agreed scope. Test both fresh and existing configuration paths when font or locale settings can persist.

Record the build ID, source manifest, translation digest, Bible and prefix versions, tools and commands, font hashes and licenses, tested routes/surfaces, warnings, and known limitations.

## Release contents

Include only intended patch files, concise installation/removal instructions, checksums, tested game version, target locale, known limitations, and required third-party notices. Do not package staging data, source archives, unrelated backups, tool caches, or copyrighted game assets not authorized for redistribution.
