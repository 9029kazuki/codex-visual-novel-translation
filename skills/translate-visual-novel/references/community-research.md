# Multilingual canon and community research

## Separate facts from target-locale convention

Research engine behavior, archive formats, canon, worldbuilding, relationships, knowledge state, and character voice in any language. Rank evidence by proximity and authority, not by language.

Use target-language sources specifically when deciding localized names, established franchise terminology, register, punctuation, historical translation practice, and target-audience expectations.

An official fact source and a target-locale usage source may be different. Record both when they answer different questions.

## Evidence lanes

Maintain three lanes in `research/sources.jsonl`:

1. `engine`: exact-version extraction, encoding, reinsertion, repacking, font, and runtime behavior.
2. `canon`: in-game text, official sites, manuals, interviews, setting books, reliable reference works, and carefully checked community analysis.
3. `target-locale`: official localizations, established franchise translations, dictionaries, style references, mature patches, guides, and target-language discussion.

Each record should contain a URL or local evidence identifier, title, access date, evidence language, source type, authority assessment, version scope, and concrete claims. Save useful excerpts only within copyright limits; prefer concise paraphrases and exact line or page references.

## Search strategy

Search the exact title, release, engine, extensions, executable name, publisher, and platform. Repeat important technical queries in the source language, English, and languages used by active reverse-engineering communities.

Search target-locale terminology separately using the title, character names, franchise name, official translation, glossary, guide, wiki, localization, and fan translation equivalents in that locale.

Do not treat search snippets as evidence. Open the source, verify it discusses the correct release, and record what it proves.

## Canon and voice outputs

Build structured records for:

- canonical names, readings, aliases, localized names, and scope;
- role, age or status when relevant, affiliations, relationships, secrets, and route-specific knowledge;
- first- and second-person forms, address patterns, formality, dialect, sentence length, aggression, humor, verbal tics, and emotional shifts;
- spoiler boundaries and the scene where each fact becomes available;
- short source examples and approved target-language renderings.

Do not flatten voice into labels such as “gentle” or “tsundere.” Record observable linguistic behavior.

## Decision handling

- Lock a term only when evidence and target-language rationale are sufficient.
- Mark uncertain readings or names as pending rather than inventing certainty.
- When canon conflicts with established target-locale convention, record the conflict and the coordinator’s decision.
- Keep proposals from delegated agents separate from accepted global decisions.
- Freeze a versioned snapshot before each translation cohort.
