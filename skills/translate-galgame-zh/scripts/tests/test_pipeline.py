"""Behavioral regressions using artificial fixtures, never release evidence."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audit_project as audit
import pipeline_common as common
import build_shared_prefix as prefix
import build_context_bundle as bundle
import record_cache_probe as probe
import create_review_report as declare
import apply_review_delta as review
import validate_translation as validator
import set_job_status as status_tool
import merge_jobs as merge
import plan_jobs as planner
import emit_chunk


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def js(path, value):
    write(path, json.dumps(value, ensure_ascii=False) + "\n")


def jl(path, rows):
    write(path, "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def invoke(module, *args):
    stdout, stderr = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "argv", [module.__file__, *map(str, args)]), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = module.main()
        except SystemExit as exc:
            code = exc.code
    return code, stdout.getvalue(), stderr.getvalue()


def fixture(root, count=12, job_count=3):
    js(root / "project.json", {"schema_version": 2, "game_name": "Synthetic regression fixture; no game tested"})
    js(root / "run-state.json", {"stage": "plan-approved", "history": [{"stage": stage, "evidence": ["project.json"]} for stage in audit.STAGES[:6]]})
    js(root / "source/file-manifest.json", {"file_count": 1})
    jl(root / "research/sources.jsonl", [{"lane": lane, "url": "https://example.invalid/test", "title": "Fixture", "claims": ["Synthetic only"], "source_language": "ja", "source_type": "local-test", "authority": "local-test", "retrieved_at": "2026-09-07", "scope": "fixture", "confidence": "high"} for lane in ("engine", "canon", "target-locale")])
    write(root / "research/unpack-notes.md", "Synthetic fixture only; not a real unpack/repack result.\n")
    js(root / "qa/roundtrip-report.json", {"passed": True, "synthetic": True})
    for name in ("input", "unpacked", "repacked"):
        write(root / f"staging/roundtrip/{name}/fixture.txt", "test")
    rows = []
    for i in range(count):
        j = i * job_count // count
        route = ("common", "misaki", "rei")[j % 3]
        row = {"id": f"s{j}:{i:06d}", "file": f"s{j}.ks", "order": i, "route": route, "scene_id": f"scene-{j}",
               "kind": "dialogue", "speaker": "玲" if route == "rei" else "美咲", "text": f"こんにちは。約束を覚えている？{i}[wait]", "protected_tokens": ["[wait]"]}
        row["source_hash"] = common.digest_value(row)
        rows.append(row)
    jl(root / "extracted/source.jsonl", rows)
    js(root / "extracted/script-map.json", {"nodes": [{"id": f"scene-{j}"} for j in range(job_count)], "edges": []})
    js(root / "extracted/control-token-report.json", {"engines": ["synthetic"]})
    js(root / "bible/version.json", {"frozen": True, "version": 1})
    write(root / "bible/world.md", "A synthetic school story with no claim of real game evidence.\n")
    write(root / "bible/honorifics.md", "Use the explicit approved honorific policy in this fixture.\n")
    js(root / "bible/characters.json", {"characters": [{"id": "misaki", "name": "美咲", "style": "gentle", "source_url": "https://example.invalid/a"}, {"id": "rei", "name": "玲", "style": "direct"}]})
    js(root / "bible/voice.json", {"narrator": {"style": "plain"}, "characters": {"misaki": {"style": "gentle"}, "rei": {"style": "direct"}}})
    js(root / "bible/route-knowledge.json", {"global": {"secret": "do not reveal the promise early"}, "routes": {"common": {}, "misaki": {}, "rei": {}}})
    jl(root / "bible/calibration.jsonl", [{"speaker": "美咲", "source": "こんにちは。", "translation": "你好。"}])
    write(root / "bible/glossary.tsv", "source\ttarget\treading\tcategory\tstatus\tscope\tsource_url\tnotes\n約束\t约定\tやくそく\tnoun\tlocked\tglobal\thttps://example.invalid\tKeep meaning\n")
    js(root / "planning/translation-decisions.json", {"accepted": [{"rule": "Keep ambiguous subjects ambiguous"}], "pending": []})
    jobs = []
    for j in range(job_count):
        scene = [row for row in rows if row["scene_id"] == f"scene-{j}"]
        jobs.append({"job_id": f"job-{j:04d}", "status": "pending", "entry_ids": [row["id"] for row in scene], "route": scene[0]["route"],
            "scene_ids": [f"scene-{j}"], "source_files": [f"s{j}.ks"], "source_digest": bundle.source_digest(scene), "bible_version": 1,
            "plan_approved": True, "context_notes": "Synthetic isolated scene; explicit closure reviewed.", "predecessors": [], "adjacent_entry_ids": [],
            "dependency_scope": {"mode": "selected", "approved": True, "rationale": "Fixture has no indirect characters", "characters": ["rei" if scene[0]["route"] == "rei" else "misaki"], "routes": [scene[0]["route"]]}})
    jl(root / "planning/jobs.jsonl", jobs)
    return rows, jobs


class PipelineTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("LOCALIZE_TEST_ROOT", str(Path.cwd() / "work/localize-regression"))).resolve()
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="case-", dir=base)
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(base))
        self.rows, self.jobs = fixture(self.root)
        self.ok(prefix, self.root)
        self.manifest = self.root / common.read_json(self.root / "contexts/shared-prefix/current.json")["manifest"]

    def tearDown(self):
        self.temp.cleanup()

    def ok(self, module, *args):
        result = invoke(module, *args)
        self.assertEqual(result[0], 0, result[2])
        return json.loads(result[1]) if result[1].strip() else None

    def build_all(self):
        self.ok(bundle, self.root, "--all-pending")

    def job_dir(self, n=0):
        return common.bundle_dir(self.root, self.jobs[n]["job_id"])

    def review_inputs(self):
        self.build_all()
        job = self.jobs[0]
        source = self.job_dir() / "source.jsonl"
        draft = self.root / "translations/drafts/job-0000.jsonl"
        delta = self.root / "reviews/job-0000.jsonl"
        report = self.root / "reviews/job-0000.report.json"
        approved = self.root / "translations/approved/job-0000.jsonl"
        jl(draft, [{"id": x, "translation": "你好，还记得那个约定吗？[wait]"} for x in job["entry_ids"]])
        jl(delta, [])
        return source, draft, delta, report, approved

    def declaration(self, source, draft, delta, report, outcome="passed"):
        return self.ok(declare, source, draft, delta, "--job-id", "job-0000", "--reviewer", "reviewer-1", "--translator", "translator-1", "--all-entries-reviewed", "--outcome", outcome, "--report", report)

    def test_pending_and_provenance_do_not_change_prefix(self):
        old = common.read_json(self.manifest)["prefix_id"]
        decisions = common.read_json(self.root / "planning/translation-decisions.json")
        decisions["pending"].append({"source": "unapproved"})
        js(self.root / "planning/translation-decisions.json", decisions)
        data = common.read_json(self.root / "bible/characters.json")
        data["characters"][0]["source_url"] = "https://example.invalid/new-source"
        js(self.root / "bible/characters.json", data)
        js(self.root / "bible/version.json", {"frozen": True, "version": 2})
        self.assertEqual(self.ok(prefix, self.root, "--expected-prefix-tokens", "1234")["prefix_id"], old)

    def test_old_cohorts_and_targeted_invalidation(self):
        self.build_all()
        changed = common.read_json(self.root / "bible/characters.json")
        changed["characters"][0]["style"] = "more reserved"
        js(self.root / "bible/characters.json", changed)
        js(self.root / "bible/version.json", {"frozen": True, "version": 2})
        self.ok(prefix, self.root)
        self.assertEqual(audit.validate_gate(self.root, "plan-approved"), [])
        self.assertTrue(common.validate_bundle(self.root, self.jobs[0]))
        self.assertEqual(common.validate_bundle(self.root, self.jobs[2]), [])

    def test_unknown_dependency_scope_is_rejected(self):
        self.jobs[0]["dependency_scope"]["characters"] = ["missing-person"]
        jl(self.root / "planning/jobs.jsonl", self.jobs)
        self.assertNotEqual(invoke(bundle, self.root, "job-0000")[0], 0)

    def test_bundle_content_and_context_are_verified(self):
        self.build_all()
        self.assertEqual(common.validate_bundle(self.root, self.jobs[0]), [])
        write(self.job_dir() / "chunks/chunk-0001.source.model.jsonl", "corrupt\n")
        self.assertTrue(common.validate_bundle(self.root, self.jobs[0]))
        self.jobs[1]["prior_summary"] = "changed meaning"
        self.assertTrue(common.validate_bundle(self.root, self.jobs[1]))

    def test_failed_rebuild_preserves_old_pointer(self):
        self.build_all()
        pointer = self.root / "contexts/job-0000/current.json"
        before = pointer.read_bytes()
        self.assertNotEqual(invoke(bundle, self.root, "job-0000", "--input-budget-tokens", "10")[0], 0)
        self.assertEqual(pointer.read_bytes(), before)
        self.assertEqual(common.validate_bundle(self.root, self.jobs[0]), [])

    def test_short_lines_are_split_by_serialized_budget(self):
        rows = [{"id": f"short:{i:06d}", "kind": "dialogue", "speaker": "美咲", "text": "え？", "protected_tokens": [], "scene_id": "same"} for i in range(20000)]
        plan, coverage, _ = bundle.build_chunk_artifacts(rows)
        self.assertGreater(plan["chunk_count"], 1)
        self.assertTrue(coverage["valid"])
        self.assertTrue(all(x["estimated_input_tokens"] <= 32000 and x["estimated_output_tokens"] <= 8192 for x in plan["chunks"]))
        self.assertEqual([x for chunk in plan["chunks"] for x in chunk["primary_entry_ids"]], [x["id"] for x in rows])

    def test_single_huge_entry_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError, "single entry"):
            bundle.build_chunk_artifacts([{**self.rows[0], "text": "長"*40000}])

    def test_batch_reuses_source_parsing(self):
        fixture(self.root, count=2000, job_count=20)
        self.ok(prefix, self.root)
        result = self.ok(bundle, self.root, "--all-pending")
        self.assertEqual(len(result["jobs"]), 20)
        self.assertLess(result["input_snapshot"]["parsed_jsonl_records"], 2200)

    def test_standalone_keeps_frozen_decisions(self):
        self.ok(bundle, self.root, "job-0000", "--standalone")
        directory = self.job_dir()
        state = common.read_json(directory / "bundle-status.json")
        self.assertTrue(state["shared_prefix_id"])
        packet = self.ok(emit_chunk, self.root, "job-0000", "chunk-0001")
        self.assertIn("Keep ambiguous subjects", packet["context"])

    def test_missing_failed_and_self_review_are_rejected(self):
        source, draft, delta, report, approved = self.review_inputs()
        args = (source, draft, delta, "--job-id", "job-0000", "--report", report, "--approved-output", approved, "--verify-existing-report")
        self.assertNotEqual(invoke(review, *args)[0], 0)
        self.assertFalse(report.exists())
        self.assertFalse(approved.exists())
        self.declaration(source, draft, delta, report, "needs-resolution")
        old = report.read_bytes()
        self.assertNotEqual(invoke(review, *args)[0], 0)
        self.assertEqual(report.read_bytes(), old)
        self.assertNotEqual(invoke(declare, source, draft, delta, "--job-id", "job-0000", "--reviewer", "same", "--translator", "same", "--all-entries-reviewed", "--outcome", "passed", "--report", report)[0], 0)

    def test_sparse_review_materializes_and_keeps_declaration(self):
        source, draft, delta, report, approved = self.review_inputs()
        jl(delta, [{"id": self.jobs[0]["entry_ids"][1], "reviewer_translation": "你还记得那次约定吗？[wait]", "reason": "修正语气", "severity": "minor"}])
        self.declaration(source, draft, delta, report)
        old = report.read_bytes()
        self.ok(review, source, draft, delta, "--job-id", "job-0000", "--report", report, "--approved-output", approved)
        self.assertEqual(report.read_bytes(), old)
        rows = common.read_jsonl(approved)
        self.assertIn("那次", rows[1]["translation"])
        self.assertIn("source_hash", rows[0])
        result = self.ok(validator, source, approved, "--glossary", self.root / "bible/glossary.tsv")
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["warnings"], 0)
        write(draft, draft.read_text(encoding="utf-8").replace("你好", "再见"))
        self.assertNotEqual(invoke(review, source, draft, delta, "--job-id", "job-0000", "--report", report)[0], 0)

    def test_cache_aggregate_and_negative_boundary_rejected(self):
        output = self.root / "qa/cache/test.json"
        self.assertNotEqual(invoke(probe, self.manifest, output, "--input-tokens", "60000", "--cached-input-tokens", "12000", "--calls", "3", "--expected-prefix-tokens", "10000")[0], 0)
        self.assertNotEqual(invoke(probe, self.manifest, output, "--input-tokens", "100", "--cached-input-tokens", "0", "--expected-prefix-tokens", "-1")[0], 0)

    def test_cache_coverage_needs_rendered_boundary_and_request_id(self):
        output = self.root / "qa/cache/test.json"
        self.ok(probe, self.manifest, output, "--input-tokens", "20000", "--cached-input-tokens", "12000", "--expected-prefix-tokens", "10000")
        self.assertIsNone(common.read_json(output)["passed"])
        self.ok(probe, self.manifest, output, "--input-tokens", "20000", "--cached-input-tokens", "12000", "--expected-prefix-tokens", "10000", "--boundary-kind", "rendered-prefix", "--request-id", "r1")
        self.assertTrue(common.read_json(output)["passed"])
        self.assertIsNone(common.read_json(output)["cache_write_tokens"])

    def test_cache_weighted_aggregation_and_deduplication(self):
        usage = self.root / "usage.jsonl"
        output = self.root / "usage-report.json"
        a = {"request_id": "a", "input_tokens": 100, "cached_input_tokens": 90, "cache_write_tokens": 10, "output_tokens": 5}
        b = {"request_id": "b", "input_tokens": 900, "cached_input_tokens": 90, "cache_write_tokens": 0, "output_tokens": 5}
        jl(usage, [a, b, a])
        self.ok(probe, self.manifest, output, "--usage-jsonl", usage)
        report = common.read_json(output)
        self.assertEqual(report["calls"], 2)
        self.assertAlmostEqual(report["cache_rate"], .18)
        jl(usage, [a, {**a, "input_tokens": 200}])
        self.assertNotEqual(invoke(probe, self.manifest, output, "--usage-jsonl", usage)[0], 0)

    def test_short_term_is_not_shadowed_at_separate_occurrence(self):
        short = {"source": "会長", "target": "会长"}
        long = {"source": "生徒会長", "target": "学生会主席"}
        self.assertFalse(validator.glossary_row_is_shadowed(short, [short, long], "生徒会長と会長", "学生会主席和那个人"))
        self.assertTrue(validator.glossary_row_is_shadowed(short, [short, long], "生徒会長", "学生会主席"))

    def test_legal_status_transitions_and_atomic_batch(self):
        path = self.root / "planning/jobs.jsonl"
        before = path.read_bytes()
        self.assertNotEqual(invoke(status_tool, path, "job-0000", "merged")[0], 0)
        self.assertEqual(path.read_bytes(), before)
        self.ok(status_tool, path, "job-0000", "assigned", "--also-job", "job-0001", "--from-status", "pending")
        self.assertEqual([x["status"] for x in common.read_jsonl(path)][:2], ["assigned", "assigned"])

    def test_font_gate_requires_independent_evidence(self):
        js(self.root / "qa/playtest-report.json", {"passed": True})
        self.assertTrue(audit.validate_gate(self.root, "playtested"))

    def test_plan_cannot_overwrite_existing_work(self):
        self.assertNotEqual(invoke(planner, self.root / "extracted/source.jsonl", self.root / "planning/jobs.jsonl")[0], 0)

    def test_job_identity_survives_an_earlier_scene_insertion(self):
        source = self.root / "extracted/source.jsonl"
        first, second = self.root / "planning/proposal1.jsonl", self.root / "planning/proposal2.jsonl"
        self.ok(planner, source, first)
        initial = {tuple(job["entry_ids"]): job["job_id"] for job in common.read_jsonl(first)}
        extra = {**self.rows[0], "id": "prologue:000000", "scene_id": "prologue"}
        jl(source, [extra, *self.rows])
        self.ok(planner, source, second)
        updated = {tuple(job["entry_ids"]): job["job_id"] for job in common.read_jsonl(second)}
        self.assertTrue(all(updated[ids] == identity for ids, identity in initial.items()))

    def test_frozen_decision_source_still_checks_live_head(self):
        frozen = self.root / "planning/frozen-decisions.json"
        js(frozen, common.read_json(self.root / "planning/translation-decisions.json"))
        new = self.ok(prefix, self.root, "--decisions", frozen)
        self.assertEqual(new["prefix_id"], common.read_json(self.manifest)["prefix_id"])
        self.assertNotEqual(new["manifest"], str(self.manifest))
        self.build_all()
        self.assertEqual(common.validate_bundle(self.root, self.jobs[0]), [])
        js(self.root / "planning/translation-decisions.json", {"accepted": [{"rule": "Change a global interpretation"}]})
        self.assertTrue(common.validate_bundle(self.root, self.jobs[0]))

    def test_invalid_delta_cannot_create_passing_declaration(self):
        source, draft, delta, report, approved = self.review_inputs()
        jl(delta, [{"id": self.jobs[0]["entry_ids"][0], "reviewer_translation": "你好，约定。[wait]", "reason": "test", "severity": "critical"}])
        self.assertNotEqual(invoke(declare, source, draft, delta, "--job-id", "job-0000", "--reviewer", "reviewer", "--translator", "translator", "--all-entries-reviewed", "--outcome", "passed", "--report", report)[0], 0)
        self.assertFalse(report.exists())

    def test_interrupted_snapshot_write_keeps_previous_bundle(self):
        self.build_all()
        pointer = self.root / "contexts/job-0000/current.json"
        before = pointer.read_bytes()
        original = bundle.atomic_text
        writes = []
        def interrupted(path, value):
            writes.append(path)
            if len(writes) == 3:
                raise OSError("simulated interrupted disk write")
            return original(path, value)
        with mock.patch.object(bundle, "atomic_text", side_effect=interrupted):
            self.assertNotEqual(invoke(bundle, self.root, "job-0000", "--chunk-overlap-entries", "2")[0], 0)
        self.assertEqual(pointer.read_bytes(), before)
        self.assertEqual(common.validate_bundle(self.root, self.jobs[0]), [])

    def test_full_merge_ignores_archives_and_qa_binds_inputs(self):
        self.build_all()
        for job in self.jobs:
            job_id = job["job_id"]
            source = common.bundle_dir(self.root, job_id) / "source.jsonl"
            draft = self.root / f"translations/drafts/{job_id}.jsonl"
            delta = self.root / f"reviews/{job_id}.jsonl"
            report = self.root / f"reviews/{job_id}.report.json"
            approved = self.root / f"translations/approved/{job_id}.jsonl"
            jl(draft, [{"id": entry, "translation": "你好，还记得那个约定吗？[wait]"} for entry in job["entry_ids"]])
            jl(delta, [])
            self.ok(declare, source, draft, delta, "--job-id", job_id, "--reviewer", "independent-fixture-review", "--translator", "fixture-author", "--all-entries-reviewed", "--outcome", "passed", "--report", report)
            self.ok(review, source, draft, delta, "--job-id", job_id, "--report", report, "--approved-output", approved)
            job["status"] = "approved"
        jl(self.root / "planning/jobs.jsonl", self.jobs)
        write(self.root / "translations/approved/archive/obsolete.jsonl", "invalid old backup must not be merged")
        final = self.root / "translations/final.jsonl"
        self.ok(merge, self.root / "extracted/source.jsonl", self.root / "translations/approved", final, "--jobs-jsonl", self.root / "planning/jobs.jsonl")
        self.assertEqual([row["id"] for row in common.read_jsonl(final)], [row["id"] for row in self.rows])
        self.ok(validator, self.root / "extracted/source.jsonl", final, "--glossary", self.root / "bible/glossary.tsv", "--report", self.root / "qa/global.json")
        self.assertEqual(audit.validate_gate(self.root, "validated"), [])
        write(final, final.read_text(encoding="utf-8").replace("你好", "再见"))
        self.assertTrue(audit.validate_gate(self.root, "validated"))

    def test_font_evidence_paths_and_build_binding(self):
        js(self.root / "qa/playtest-report.json", {"passed": True})
        js(self.root / "qa/repack-report.json", {"passed": True, "build_digest": "fixture-build"})
        js(self.root / "qa/font-coverage.json", {"passed": True, "missing_count": 0, "build_digest": "fixture-build"})
        profiles = {profile: {surface: {"status": "pass", "evidence": ["qa/synthetic-evidence.txt"]} for surface in ("body", "namebox", "choice", "history", "settings", "save_title")} for profile in ("fresh", "existing")}
        js(self.root / "qa/font-runtime-report.json", {"passed": True, "build_digest": "fixture-build", "profiles": profiles})
        self.assertTrue(audit.validate_gate(self.root, "playtested"))
        write(self.root / "qa/synthetic-evidence.txt", "Synthetic test only; no game run.")
        self.assertEqual(audit.validate_gate(self.root, "playtested"), [])
        js(self.root / "qa/font-coverage.json", {"passed": True, "missing_count": 0, "build_digest": "old-build"})
        self.assertTrue(audit.validate_gate(self.root, "playtested"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
