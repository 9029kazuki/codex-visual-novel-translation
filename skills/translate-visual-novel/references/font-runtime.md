# Font coverage and runtime selection

Static Unicode coverage and actual in-game rendering are separate gates:

1. The intended font contains every required target character.
2. The engine actually selects that font, face, size, shaping path, and fallback chain at runtime.

A passing cmap audit proves only the first point.

## Build the required character set

Collect visible text from the final approved translation after removing confirmed control tokens. Include dialogue, narration, names, choices, UI, history, save titles, settings, route labels, and any generated text. Add representative target-script probes, but never use a few probes instead of the full character union.

Record each font path, byte size, SHA-256, collection face index, family/full/PostScript names, Unicode cmap size, and license. Use `scripts/audit_font_coverage.py` against the exact files intended for release.

## Diagnose the runtime chain

Trace all possible font selectors:

- archive and loose-file loading order;
- language and locale mappings;
- theme, message-window, name-box, backlog, choice, and save-screen styles;
- embedded family or face names rather than filenames;
- collection face indices and fallback lists;
- user configuration, persistent variables, save data, and renderer caches;
- inline font, size, ruby, or style controls in the script.

Patch the earliest stable selector that controls all relevant surfaces. Avoid global byte replacement when a structured resource can be edited.

## Writing-system concerns

- CJK: verify simplified/traditional forms, fallback order, ruby, punctuation metrics, and line breaking.
- Latin, Greek, and Cyrillic: verify diacritics, smart punctuation, casing, and text expansion.
- Arabic and Hebrew: verify shaping, bidirectional order, punctuation mirroring, mixed numbers, and alignment; cmap coverage is insufficient.
- Indic and Southeast Asian scripts: verify combining marks, cluster shaping, mark placement, and engine line breaking.
- Emoji and supplementary-plane characters: verify the renderer supports the relevant cmap format and color/monochrome fallback.

## Runtime proof

Test both a fresh configuration and an existing user-state path. Capture evidence from dialogue, name boxes, choices, history, settings, and save/load screens. If changing locale or deleting a test preference changes the font, the persistent configuration is part of the loading chain and must be handled by the patch or documented.

Classify failures before changing files:

| Symptom | Likely cause |
| --- | --- |
| Missing isolated characters | cmap gap or wrong fallback face |
| Correct glyphs but wrong style | runtime selected another face |
| Characters appear separated or reversed | missing shaping or bidi support |
| Duplicate text at different sizes | parallel language/ruby layer, not a cmap issue |
| Works only after clearing settings | persistent font or locale selection |

The release report should include the static coverage result, runtime surfaces tested, font hashes and licenses, configuration paths tested, and unresolved rendering risks.
