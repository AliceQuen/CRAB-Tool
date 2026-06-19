#!/usr/bin/env python3
from test_crab_recovery_state_builder_v2 import *  # noqa: F401,F403

'''
"""Unit tests for crab_recovery_task_builder.py."""

from __future__ import annotations

import importlib.util
import json
import re
import runpy
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("crab_recovery_task_builder.py")
MODULE_SPEC = importlib.util.spec_from_file_location(
    "crab_recovery_task_builder", MODULE_PATH
)
builder = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(builder)

TEMPLATE_PATH = Path(__file__).with_name("crab3_recovery_template.py")


def write_original_cfg(path: Path) -> None:
    path.write_text(
        "from WMCore.Configuration import Configuration\n"
        "config = Configuration()\n"
        "config.section_('General')\n"
        "config.General.requestName = 'crab3_refactor_JpsiJpsiPhi_6Run2024Hv1MINIAOD'\n"
        "config.section_('JobType')\n"
        "config.JobType.outputFiles = ['mymultilep_Run2024Hv1.root']\n"
        "config.JobType.pyCfgParams = [\n"
        "    'runOnMC=False',\n"
        "    'era=Run2024H',\n"
        "    'outputFile=mymultilep_Run2024Hv1.root',\n"
        "    'analysisMode=JpsiJpsiPhi',\n"
        "    'numThreads=4',\n"
        "    'numStreams=4',\n"
        "]\n"
        "config.JobType.numCores = 1\n"
        "config.JobType.maxMemoryMB = 2000\n"
        "config.section_('Data')\n"
        "config.Data.splitting = 'LumiBased'\n"
        "config.Data.unitsPerJob = 40\n"
        "config.Data.publication = False\n"
        "config.Data.outputDatasetTag = 'crab3_refactor_JpsiJpsiPhi_6Run2024Hv1MINIAOD'\n"
        "config.Data.lumiMask = '/tmp/chiw/original_lumi_mask.json'\n"
        "config.section_('Site')\n"
        "config.Site.storageSite = 'T2_TEST_SITE'\n"
    )


def make_render_task(tmp: Path, cfg_path: Path) -> dict[str, object]:
    return {
        "task_dir": "crab_parent",
        "cfg_path": str(cfg_path),
        "request_name": cfg_path.stem,
        "recover_request_name": f"{cfg_path.stem}__recover1",
        "preserved_not_finished_lumis": str(tmp / "report" / "notFinishedLumis.json"),
        "task_not_finished_lumis": str(tmp / "task_results" / "notFinishedLumis.json"),
        "recover_cfg": str(tmp / "recovery_cache" / "configs" / "child.py"),
    }


def install_fake_wmcore(tmp: Path) -> None:
    wmcore_dir = tmp / "WMCore"
    wmcore_dir.mkdir()
    (wmcore_dir / "__init__.py").write_text("")
    (wmcore_dir / "Configuration.py").write_text(
        "from types import SimpleNamespace\n"
        "\n"
        "class Configuration:\n"
        "    def section_(self, name):\n"
        "        section = SimpleNamespace()\n"
        "        setattr(self, name, section)\n"
        "        return section\n"
    )


@contextmanager
def prepend_sys_path(path: Path):
    sys.path.insert(0, str(path))
    try:
        yield
    finally:
        sys.path = [entry for entry in sys.path if entry != str(path)]


def render_template_with_task(tmp: Path, task: dict[str, object], template_text: str) -> object:
    install_fake_wmcore(tmp)
    template_copy = tmp / "crab3_recovery_template.py"
    template_copy.write_text(template_text)
    rendered_path = builder.render_recovery_config(task, template_copy)
    with prepend_sys_path(tmp):
        namespace = runpy.run_path(str(rendered_path))
    return namespace["config"]


def reset_template_overrides(template_text: str) -> str:
    normalized = template_text
    replacements = [
        (r"^RECOVERY_UNITS_PER_JOB = .*$", "RECOVERY_UNITS_PER_JOB = None"),
        (r"^RECOVERY_SPLITTING = .*$", "RECOVERY_SPLITTING = None"),
        (r"^RECOVERY_NUM_CORES = .*$", "RECOVERY_NUM_CORES = None"),
        (r"^RECOVERY_MAX_MEMORY_MB = .*$", "RECOVERY_MAX_MEMORY_MB = None"),
    ]
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.MULTILINE)
    normalized = re.sub(
        r"RECOVERY_PYCFG_PARAM_OVERRIDES = \{\n(?:.*\n)*?\}",
        'RECOVERY_PYCFG_PARAM_OVERRIDES = {\n    "numThreads": 1,\n    "numStreams": 0,\n}',
        normalized,
        flags=re.MULTILINE,
    )
    normalized = re.sub(
        r"RECOVERY_OVERRIDES = \{\n(?:.*\n)*?\}",
        'RECOVERY_OVERRIDES = {\n    # "Site.storageSite": "T2_CH_CERN",\n    # "Data.publication": False,\n}',
        normalized,
        flags=re.MULTILINE,
    )
    return normalized


class CrabRecoveryTaskBuilderTest(unittest.TestCase):
    def test_plan_accepts_legacy_killed_task_without_payload_and_resolves_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "crab3_refactor_JpsiJpsiPhi_6Run2024Hv1MINIAOD.py"
            write_original_cfg(cfg_path)

            task_dir = tmp / "crab_crab3_refactor_JpsiJpsiPhi_6Run2024Hv1MINIAOD"
            task_dir.mkdir()
            summary_path = tmp / "status_cache" / "latest_summary.json"
            summary_path.parent.mkdir()
            summary_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-04-17T12:00:00+00:00",
                        "cwd": str(tmp),
                        "query_failures": [
                            "crab_crab3_refactor_JpsiJpsiPhi_6Run2024Hv1MINIAOD"
                        ],
                        "tasks": [
                            {
                                "cfg": cfg_path.name,
                                "task_dir": task_dir.name,
                                "task_path": str(task_dir),
                                "task_name": "260411_081645:chiw_crab_crab3_refactor_JpsiJpsiPhi_6Run2024Hv1MINIAOD",
                                "server_status": "KILLED",
                                "scheduler_status": None,
                                "dashboard_url": "https://example.invalid",
                                "job_count": 0,
                                "job_states": {},
                                "failed_job_count": 0,
                                "failed_job_ids": [],
                                "query_error": "Failed to parse status JSON: Could not locate JSON payload in `crab status --json` output.",
                                "task_status_file": f"tasks/{task_dir.name}.json",
                            }
                        ],
                    }
                )
            )

            args = type(
                "Args",
                (),
                {
                    "summary_file": str(summary_path),
                    "output_dir": str(tmp / "recovery_cache"),
                    "stuck_hours": 48.0,
                    "recovery_suffix": "recover",
                },
            )
            self.assertEqual(builder.build_plan(args), 0)

            plan_path = tmp / "recovery_cache" / builder.PLAN_NAME
            plan = json.loads(plan_path.read_text())
            self.assertEqual(plan["counts"]["killed_recovery_candidate"], 1)
            self.assertEqual(plan["query_failures"], [])

            task = builder.find_task(plan, task_dir.name)
            self.assertEqual(task["classification"], "killed_recovery_candidate")
            self.assertEqual(
                task["recover_request_name"],
                "crab3_refactor_JpsiJpsiPhi_6Run2024Hv1MINIAOD__recover1",
            )
            self.assertEqual(
                task["child_task_dir"],
                "crab_crab3_refactor_JpsiJpsiPhi_6Run2024Hv1MINIAOD__recover1",
            )

            resolve_args = type(
                "ResolveArgs",
                (),
                {"plan_file": str(plan_path), "task": task_dir.name},
            )
            self.assertEqual(builder.resolve_lumi_mask(resolve_args), 0)
            plan = json.loads(plan_path.read_text())
            task = builder.find_task(plan, task_dir.name)
            self.assertEqual(task["resolved_lumi_action"], "submit")
            self.assertEqual(
                task["resolved_lumi_source"], "original_lumi_mask_fallback"
            )
            self.assertEqual(task["resolved_lumi_mask"], "/tmp/chiw/original_lumi_mask.json")
            self.assertTrue(task["kill_required"] is False)

    def test_record_submission_updates_lineage_and_tracked_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            lineage_path = tmp / "recovery_cache" / builder.LINEAGE_NAME
            plan_path = tmp / "recovery_cache" / builder.PLAN_NAME
            recover_cfg = tmp / "recovery_cache" / "configs" / "child.py"
            recover_cfg.parent.mkdir(parents=True)
            recover_cfg.write_text("# cfg\n")
            child_task_path = tmp / "crab_child"
            child_task_path.mkdir()

            builder.write_json(
                lineage_path,
                {
                    "generated_at": "2026-04-17T12:00:00+00:00",
                    "nodes": {
                        "crab_parent": {
                            "task_dir": "crab_parent",
                            "task_path": str(tmp / "crab_parent"),
                            "cfg_path": str(tmp / "parent.py"),
                            "request_name": "parent",
                            "root_request_name": "parent",
                            "generation": 0,
                            "parent_task_dir": None,
                        }
                    },
                    "edges": [],
                },
            )
            builder.write_json(
                plan_path,
                {
                    "output_dir": str(tmp / "recovery_cache"),
                    "lineage_file": str(lineage_path),
                    "tasks": [
                        {
                            "task_dir": "crab_parent",
                            "classification": "killed_recovery_candidate",
                            "child_task_dir": "crab_child",
                            "child_task_path": str(child_task_path),
                            "recover_cfg": str(recover_cfg),
                            "recover_request_name": "parent__recover1",
                            "root_request_name": "parent",
                            "child_generation": 1,
                            "original_lumi_mask": "/tmp/chiw/original.json",
                            "resolved_lumi_action": "submit",
                            "resolved_lumi_source": "original_lumi_mask_fallback",
                            "resolved_lumi_mask": "/tmp/chiw/original.json",
                        }
                    ],
                },
            )

            args = type("Args", (), {"plan_file": str(plan_path), "task": "crab_parent"})
            self.assertEqual(builder.record_submission(args), 0)

            lineage = json.loads(lineage_path.read_text())
            self.assertIn("crab_child", lineage["nodes"])
            self.assertEqual(lineage["nodes"]["crab_child"]["parent_task_dir"], "crab_parent")
            self.assertEqual(lineage["edges"][0]["child"], "crab_child")

            tracked_manifest = (tmp / "recovery_cache" / builder.TRACKED_CONFIGS_NAME).read_text()
            self.assertIn(str(recover_cfg), tracked_manifest)

    def test_infer_request_lineage_handles_numbered_and_legacy_recoveries(self) -> None:
        self.assertEqual(
            builder.infer_request_lineage("root__recover2", "recover"),
            ("root", 2),
        )
        self.assertEqual(
            builder.infer_request_lineage("root_recover_recover", "recover"),
            ("root", 2),
        )

    def test_render_recovery_config_uses_default_recovery_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "parent.py"
            write_original_cfg(cfg_path)

            task = make_render_task(tmp, cfg_path)
            task["resolved_lumi_mask"] = "/tmp/chiw/missing.json"

            config = render_template_with_task(
                tmp, task, reset_template_overrides(TEMPLATE_PATH.read_text())
            )
            self.assertEqual(
                config.General.requestName,
                "parent__recover1",
            )
            self.assertEqual(config.Data.lumiMask, "/tmp/chiw/missing.json")
            self.assertEqual(config.Data.unitsPerJob, 40)
            self.assertEqual(config.Data.outputDatasetTag, "parent__recover1")
            self.assertEqual(config.Data.splitting, "LumiBased")
            self.assertEqual(
                config.JobType.pyCfgParams,
                [
                    "runOnMC=False",
                    "era=Run2024H",
                    "outputFile=mymultilep_Run2024Hv1.root",
                    "analysisMode=JpsiJpsiPhi",
                    "numThreads=1",
                    "numStreams=0",
                ],
            )
            self.assertEqual(config.JobType.numCores, 1)
            self.assertEqual(config.JobType.maxMemoryMB, 2000)

    def test_render_recovery_config_applies_overlay_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "parent.py"
            write_original_cfg(cfg_path)

            task = make_render_task(tmp, cfg_path)
            task["resolved_lumi_mask"] = "/tmp/chiw/missing.json"

            template_text = (
                reset_template_overrides(TEMPLATE_PATH.read_text())
                .replace("RECOVERY_UNITS_PER_JOB = None", "RECOVERY_UNITS_PER_JOB = 10")
                .replace("RECOVERY_SPLITTING = None", "RECOVERY_SPLITTING = 'EventAwareLumiBased'")
                .replace("RECOVERY_NUM_CORES = None", "RECOVERY_NUM_CORES = 8")
                .replace("RECOVERY_MAX_MEMORY_MB = None", "RECOVERY_MAX_MEMORY_MB = 8000")
                .replace(
                    'RECOVERY_PYCFG_PARAM_OVERRIDES = {\n    "numThreads": 1,\n    "numStreams": 0,\n}',
                    'RECOVERY_PYCFG_PARAM_OVERRIDES = {\n    "numThreads": 8,\n    "numStreams": 0,\n    "wantSummary": True,\n}',
                )
                .replace(
                    "RECOVERY_OVERRIDES = {\n    # \"Site.storageSite\": \"T2_CH_CERN\",\n    # \"Data.publication\": False,\n}",
                    "RECOVERY_OVERRIDES = {\n    'Site.storageSite': 'T2_CH_CERN',\n    'Data.publication': True,\n}",
                )
            )

            config = render_template_with_task(tmp, task, template_text)
            self.assertEqual(config.Data.unitsPerJob, 10)
            self.assertEqual(config.Data.splitting, "EventAwareLumiBased")
            self.assertEqual(config.JobType.numCores, 8)
            self.assertEqual(config.JobType.maxMemoryMB, 8000)
            self.assertEqual(
                config.JobType.pyCfgParams,
                [
                    "runOnMC=False",
                    "era=Run2024H",
                    "outputFile=mymultilep_Run2024Hv1.root",
                    "analysisMode=JpsiJpsiPhi",
                    "numThreads=8",
                    "numStreams=0",
                    "wantSummary=True",
                ],
            )
            self.assertEqual(config.Site.storageSite, "T2_CH_CERN")
            self.assertTrue(config.Data.publication)

    def test_render_recovery_config_appends_new_pycfg_param_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "parent.py"
            write_original_cfg(cfg_path)

            task = make_render_task(tmp, cfg_path)
            task["resolved_lumi_mask"] = "/tmp/chiw/missing.json"

            template_text = reset_template_overrides(TEMPLATE_PATH.read_text()).replace(
                'RECOVERY_PYCFG_PARAM_OVERRIDES = {\n    "numThreads": 1,\n    "numStreams": 0,\n}',
                'RECOVERY_PYCFG_PARAM_OVERRIDES = {\n    "wantSummary": True,\n}',
            )

            config = render_template_with_task(tmp, task, template_text)
            self.assertEqual(
                config.JobType.pyCfgParams,
                [
                    "runOnMC=False",
                    "era=Run2024H",
                    "outputFile=mymultilep_Run2024Hv1.root",
                    "analysisMode=JpsiJpsiPhi",
                    "numThreads=4",
                    "numStreams=4",
                    "wantSummary=True",
                ],
            )

    def test_render_recovery_config_rejects_unresolved_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "parent.py"
            write_original_cfg(cfg_path)

            task = make_render_task(tmp, cfg_path)
            task["resolved_lumi_mask"] = "/tmp/chiw/missing.json"

            template_text = reset_template_overrides(TEMPLATE_PATH.read_text()) + '\nBROKEN = "__FOO__"\n'
            template_copy = tmp / "crab3_recovery_template.py"
            template_copy.write_text(template_text)

            with self.assertRaisesRegex(ValueError, "Unresolved placeholders"):
                builder.render_recovery_config(task, template_copy)

    def test_resolve_lumi_prefers_preserved_not_finished_lumis(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            preserved = tmp / "report" / "notFinishedLumis.json"
            preserved.parent.mkdir(parents=True)
            preserved.write_text(json.dumps({"1": [[1, 5]]}))
            task_results = tmp / "task_results" / "notFinishedLumis.json"
            task_results.parent.mkdir(parents=True)
            task_results.write_text(json.dumps({"1": [[6, 9]]}))

            action, source, path = builder.resolve_lumi_for_task(
                {
                    "classification": "recovery_candidate",
                    "preserved_not_finished_lumis": str(preserved),
                    "task_not_finished_lumis": str(task_results),
                    "original_lumi_mask": "/tmp/chiw/original.json",
                }
            )
            self.assertEqual((action, source, path), ("submit", "preserved_not_finished", str(preserved)))

    def test_resolve_lumi_uses_task_results_not_finished_when_not_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            task_results = tmp / "task_results" / "notFinishedLumis.json"
            task_results.parent.mkdir(parents=True)
            task_results.write_text(json.dumps({"1": [[1, 5]]}))

            action, source, path = builder.resolve_lumi_for_task(
                {
                    "classification": "killed_recovery_candidate",
                    "preserved_not_finished_lumis": str(tmp / "report" / "notFinishedLumis.json"),
                    "task_not_finished_lumis": str(task_results),
                    "original_lumi_mask": "/tmp/chiw/original.json",
                }
            )
            self.assertEqual((action, source, path), ("submit", "task_results_not_finished", str(task_results)))

    def test_resolve_lumi_does_not_use_lumis_to_process_as_recovery_mask(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            report_dir = tmp / "report"
            report_dir.mkdir(parents=True)
            (report_dir / "lumisToProcess.json").write_text(json.dumps({"1": [[1, 5]]}))

            action, source, path = builder.resolve_lumi_for_task(
                {
                    "classification": "recovery_candidate",
                    "preserved_not_finished_lumis": str(report_dir / "notFinishedLumis.json"),
                    "task_not_finished_lumis": str(tmp / "task_results" / "notFinishedLumis.json"),
                    "original_lumi_mask": "/tmp/chiw/original.json",
                }
            )
            self.assertEqual((action, source, path), ("error", "missing_not_finished_lumis", ""))

    def test_resolve_lumi_falls_back_to_original_mask_when_no_jobs_finished(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            action, source, path = builder.resolve_lumi_for_task(
                {
                    "classification": "recovery_candidate",
                    "job_states": {"idle": 565},
                    "preserved_not_finished_lumis": str(tmp / "report" / "notFinishedLumis.json"),
                    "task_not_finished_lumis": str(tmp / "task_results" / "notFinishedLumis.json"),
                    "original_lumi_mask": "/tmp/chiw/original.json",
                }
            )
            self.assertEqual(
                (action, source, path),
                ("submit", "original_lumi_mask_no_finished_jobs", "/tmp/chiw/original.json"),
            )

    def test_resolve_lumi_keeps_failing_when_some_jobs_finished_but_not_finished_lumis_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            action, source, path = builder.resolve_lumi_for_task(
                {
                    "classification": "recovery_candidate",
                    "job_states": {"finished": 1, "idle": 10},
                    "preserved_not_finished_lumis": str(tmp / "report" / "notFinishedLumis.json"),
                    "task_not_finished_lumis": str(tmp / "task_results" / "notFinishedLumis.json"),
                    "original_lumi_mask": "/tmp/chiw/original.json",
                }
            )
            self.assertEqual((action, source, path), ("error", "missing_not_finished_lumis", ""))

    def test_resolve_lumi_does_not_assume_zero_finished_when_job_states_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            action, source, path = builder.resolve_lumi_for_task(
                {
                    "classification": "recovery_candidate",
                    "job_states": {},
                    "preserved_not_finished_lumis": str(tmp / "report" / "notFinishedLumis.json"),
                    "task_not_finished_lumis": str(tmp / "task_results" / "notFinishedLumis.json"),
                    "original_lumi_mask": "/tmp/chiw/original.json",
                }
            )
            self.assertEqual((action, source, path), ("error", "missing_not_finished_lumis", ""))


if __name__ == "__main__":
    unittest.main()
'''
