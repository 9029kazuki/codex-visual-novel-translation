# Shared prefix and scene batching

## Purpose

Keep identical project-wide knowledge at the beginning of translation and review contexts. Put variable job content after it. This improves consistency and gives the host the best chance to reuse cached prefix tokens across agents and jobs.

Caching is an optimization, not a correctness dependency. A reported cache hit does not prove that a model followed the material, and a cache miss must not change the translation contract.

## Stable prefix order

`scripts/build_shared_prefix.py` renders a content-addressed prefix in this order:

1. universal translation contract and frozen language-pair profile;
2. world rules, complete character data, and complete voice data;
3. address policy, complete glossary, route knowledge, and approved examples;
4. current frozen translation decisions.

Keep wording, ordering, whitespace, serialization, and section names deterministic. Do not insert timestamps, absolute paths, agent names, job IDs, mutable status, or current-scene text into this prefix.

When a Bible or decision changes, generate a new prefix ID and bind new jobs to it. Do not overwrite an immutable prefix directory.

## Clean seed

For a long coordinator conversation, start formal translation and review agents from a clean seed rather than inheriting the entire project discussion. The seed reads each prefix section in the manifest order and verifies the recorded hash. Jobs dispatched from that seed inherit the same stable history.

Each job then receives only:

- the immutable prefix binding and job contract;
- complete source for the assigned scene or subscene;
- required adjacent source and route state;
- chunk and coverage plans;
- output paths.

## Oversized scenes

Do not reject a valid scene because its context bundle exceeds an arbitrary character threshold. Create chunks at natural boundaries such as location, time, viewpoint, choice, battle phase, or conversation transition.

Every source ID appears in exactly one primary chunk. `overlap_before` and `overlap_after` may repeat nearby records for context, but those records are never emitted from the overlap chunk. Keep a machine-readable `coverage-plan.json` proving one-to-one primary ownership.

After every chunk, validate returned IDs and protected tokens. At completion, compare the union of primary output IDs with the frozen job IDs before review begins.

## Cache observations

When the host exposes usage data, run one small probe job and record prefix ID, prefix hash, expected prefix boundary, cached input, non-cached input, model, and observation time with `record_cache_probe.py`. Treat the result as host- and model-specific rather than a permanent guarantee.
