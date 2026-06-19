#!/usr/bin/env python3
"""CLI regression tests for the crabData shell wrappers and Python helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SUBMIT_SH = SCRIPT_DIR / "submit.sh"
RESUBMIT_SH = SCRIPT_DIR / "resubmit.sh"
STATUS_SH = SCRIPT_DIR / "status.sh"
PREPARE_RECOVERY_SH = SCRIPT_DIR / "prepare_recovery_tasks.sh"
KILL_RECOVER_SH = SCRIPT_DIR / "kill_unfinished_and_submit_recover.sh"
STATUS_SNAPSHOT_PY = SCRIPT_DIR / "crab_status_snapshot.py"
RESUBMIT_PY = SCRIPT_DIR / "crab_resubmit.py"
RECOVERY_BUILDER_PY = SCRIPT_DIR / "crab_recovery_task_builder.py"
ROOT_COMPACT_MASK = {"1": [[1, 5]]}
SAMPLE_STATUS_OUTPUT = """CRAB project directory:\t\t/path/to/crab_task
Task name:\t\t\t260411_080042:chiw_crab_task
Status on the CRAB server:\tSUBMITTED
Status on the scheduler:\tSUBMITTED

{"1": {"State": "finished", "Error": [0, "OK", {}]}, "2": {"State": "failed", "Error": [8020, "File open error", {}]}}
"""


def install_fake_wmcore(root: Path) -> None:
    wmcore_dir = root / "WMCore"
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


def write_original_cfg(path: Path, original_lumi_mask: Path) -> None:
    path.write_text(
        "from WMCore.Configuration import Configuration\n"
        "config = Configuration()\n"
        "config.section_('General')\n"
        f"config.General.requestName = '{path.stem}'\n"
        "config.section_('JobType')\n"
        "config.JobType.outputFiles = ['sample.root']\n"
        "config.JobType.pyCfgParams = [\n"
        "    'runOnMC=False',\n"
        "    'era=Run2022E',\n"
        "    'outputFile=sample.root',\n"
        "    'analysisMode=JpsiJpsiPhi',\n"
        "]\n"
        "config.JobType.numCores = 1\n"
        "config.JobType.maxMemoryMB = 2000\n"
        "config.section_('Data')\n"
        "config.Data.splitting = 'LumiBased'\n"
        "config.Data.unitsPerJob = 50\n"
        "config.Data.publication = False\n"
        f"config.Data.lumiMask = '{original_lumi_mask}'\n"
        "config.section_('Site')\n"
        "config.Site.storageSite = 'T2_TEST_SITE'\n"
    )


def make_fake_tools(root: Path) -> tuple[Path, Path]:
    fake_bin = root / "bin"
    fake_bin.mkdir()
    proxy_path = root / "x509up_u_test"
    proxy_path.write_text("proxy\n")
    crab_log = root / "fake_crab.log"

    crab_script = fake_bin / "crab"
    crab_script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" >> \"${FAKE_CRAB_LOG}\"\n"
        "cmd=\"${1:-}\"\n"
        "shift || true\n"
        "case \"${cmd}\" in\n"
        "  status)\n"
        "    if [[ -n \"${FAKE_CRAB_STATUS_OUTPUT:-}\" ]]; then\n"
        "      printf '%b' \"${FAKE_CRAB_STATUS_OUTPUT}\"\n"
        "    fi\n"
        "    ;;\n"
        "  report)\n"
        "    task_path=\"\"\n"
        "    while (($#)); do\n"
        "      if [[ \"$1\" == \"-d\" && $# -ge 2 ]]; then\n"
        "        task_path=\"$2\"\n"
        "        shift 2\n"
        "        continue\n"
        "      fi\n"
        "      shift\n"
        "    done\n"
        "    if [[ -n \"${task_path}\" ]]; then\n"
        "      mkdir -p \"${task_path}/results\"\n"
        "    fi\n"
        "    case \"${FAKE_CRAB_REPORT_MODE:-}\" in\n"
        "      with_not_finished)\n"
        "        if [[ -n \"${task_path}\" ]]; then\n"
        "          printf '%s\\n' '{\"1\": [[1, 5]]}' > \"${task_path}/results/notFinishedLumis.json\"\n"
        "        fi\n"
        "        ;;\n"
        "      no_not_finished)\n"
        "        if [[ -n \"${task_path}\" ]]; then\n"
        "          printf '%s\\n' '{\"1\": [[1, 5]]}' > \"${task_path}/results/lumisToProcess.json\"\n"
        "        fi\n"
        "        ;;\n"
        "    esac\n"
        "    ;;\n"
        "esac\n"
        "exit 0\n"
    )
    crab_script.chmod(0o755)

    proxy_script = fake_bin / "voms-proxy-info"
    proxy_script.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"-path\" ]]; then\n"
        "  printf '%s\\n' \"${FAKE_PROXY_PATH}\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    proxy_script.chmod(0o755)
    return proxy_path, crab_log


def make_recovery_state(
    tmp: Path,
    status_cache_dir: Path,
    recovery_cache_dir: Path,
    *,
    classification: str,
    job_states: dict[str, int],
    has_child_attempt: bool = False,
) -> tuple[Path, Path, Path]:
    install_fake_wmcore(tmp)
    cfg_path = tmp / "sample_cfg.py"
    original_lumi_mask = tmp / "original_lumi_mask.json"
    original_lumi_mask.write_text(json.dumps(ROOT_COMPACT_MASK) + "\n")
    write_original_cfg(cfg_path, original_lumi_mask)
    task_path = tmp / "crab_sample_cfg"
    task_path.mkdir()
    report_dir = recovery_cache_dir / "reports" / "crab_sample_cfg"
    recover_cfg = recovery_cache_dir / "configs" / "sample_cfg__recover1.py"
    state_path = status_cache_dir / "latest_state.json"
    status_cache_dir.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "cwd": str(tmp),
                "families": {
                    "crab_sample_cfg": {
                        "root_task_dir": "crab_sample_cfg",
                        "root_cfg": str(cfg_path),
                        "attempt_order": ["crab_sample_cfg"]
                        if not has_child_attempt
                        else ["crab_sample_cfg", "crab_sample_cfg__recover1"],
                        "latest_attempt_id": "crab_sample_cfg"
                        if not has_child_attempt
                        else "crab_sample_cfg__recover1",
                    }
                },
                "attempts": {
                    "crab_sample_cfg": {
                        "task_dir": "crab_sample_cfg",
                        "task_path": str(task_path),
                        "cfg": str(cfg_path),
                        "cfg_path": str(cfg_path),
                        "request_name": "sample_cfg",
                        "family_id": "crab_sample_cfg",
                        "parent_attempt_id": None,
                        "generation": 0,
                        "planned_lumi_mask": ROOT_COMPACT_MASK,
                        "planned_lumi_source": "original_task_lumi_mask",
                        "original_lumi_mask": ROOT_COMPACT_MASK,
                        "status_revision": "sha256:test",
                        "status": {
                            "status_collection_state": "ok_json",
                            "job_states": job_states,
                            "failed_job_count": 0,
                            "failed_job_ids": [],
                            "jobs": {},
                        },
                        "recovery": {
                            "classification": classification,
                            "derived_from_revision": "sha256:test",
                            "executable": not has_child_attempt,
                            "has_child_attempt": has_child_attempt,
                            "resolved_lumi_action": None,
                            "resolved_lumi_source": None,
                            "resolved_lumi_mask": None,
                        },
                        "artifacts": {
                            "report_dir": str(report_dir),
                            "preserved_not_finished_lumis": str(
                                report_dir / "notFinishedLumis.json"
                            ),
                            "task_not_finished_lumis": str(
                                task_path / "results" / "notFinishedLumis.json"
                            ),
                            "task_processed_lumis": str(
                                task_path / "results" / "processedLumis.json"
                            ),
                            "task_lumis_to_process": str(
                                task_path / "results" / "lumisToProcess.json"
                            ),
                            "next_recover_cfg": str(recover_cfg),
                            "next_recover_request_name": "sample_cfg__recover1",
                            "next_child_task_dir": "crab_sample_cfg__recover1",
                            "next_child_task_path": str(tmp / "crab_sample_cfg__recover1"),
                            "next_planned_lumi_mask_file": str(
                                recovery_cache_dir / "lumimasks" / "sample_cfg__recover1.json"
                            ),
                        },
                    }
                },
            }
        )
    )
    return cfg_path, task_path, state_path


class CrabCliWrapperTest(unittest.TestCase):
    maxDiff = None

    def base_env(self) -> dict[str, str]:
        env = os.environ.copy()
        for key in ("CMSSW_BASE", "CMSSW_RELEASE_BASE", "SCRAM_ARCH", "X509_USER_PROXY"):
            env.pop(key, None)
        return env

    def run_command(
        self, command: list[str], *, env: dict[str, str], cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd or SCRIPT_DIR,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_submit_help_short_circuits_preflight(self) -> None:
        env = self.base_env()
        completed = self.run_command(["bash", str(SUBMIT_SH), "--help"], env=env)
        self.assertEqual(completed.returncode, 0)
        self.assertIn("Usage: ./submit.sh", completed.stdout)
        self.assertNotIn("CMSSW environment is not active", completed.stderr)

    def test_prepare_recovery_help_short_circuits_preflight(self) -> None:
        env = self.base_env()
        completed = self.run_command(
            ["bash", str(PREPARE_RECOVERY_SH), "--help"], env=env
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("Usage: ./prepare_recovery_tasks.sh", completed.stdout)
        self.assertNotIn("CMSSW environment is not active", completed.stderr)

    def test_submit_requires_cmssw_before_normal_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                }
            )

            completed = self.run_command(
                ["bash", str(SUBMIT_SH), "--dry-run", "--manifest", str(manifest_path)],
                env=env,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("CMSSW environment is not active", completed.stderr)

    def test_submit_execute_cli_overrides_dry_run_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                    "DRY_RUN": "1",
                }
            )

            completed = self.run_command(
                ["bash", str(SUBMIT_SH), "--execute", "--manifest", str(manifest_path)],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertTrue(crab_log.exists())
            self.assertIn(f"submit -c {cfg_path}", crab_log.read_text())

    def test_submit_dry_run_cli_overrides_execute_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                    "DRY_RUN": "0",
                }
            )

            completed = self.run_command(
                ["bash", str(SUBMIT_SH), "--dry-run", "--manifest", str(manifest_path)],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn(f"crab submit -c {cfg_path}", completed.stdout)
            self.assertFalse(crab_log.exists(), msg=crab_log.read_text() if crab_log.exists() else "")

    def test_resubmit_use_cached_status_cli_overrides_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")
            task_dir = tmp / "crab_sample_cfg"
            status_cache_dir = tmp / "status_cache"
            status_cache_dir.mkdir()
            state_path = status_cache_dir / "latest_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "query_failures": [],
                        "attempts": {
                            str(task_dir): {
                                "task_dir": str(task_dir),
                                "status": {
                                    "failed_job_ids": ["7", "9"],
                                    "failed_job_count": 2,
                                },
                            }
                        },
                    }
                )
            )

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                    "USE_CACHED_STATUS": "0",
                }
            )

            completed = self.run_command(
                [
                    "bash",
                    str(RESUBMIT_SH),
                    "--dry-run",
                    "--use-cached-status",
                    "--manifest",
                    str(manifest_path),
                    "--status-cache-dir",
                    str(status_cache_dir),
                ],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn(f"crab resubmit -d {task_dir} --jobids", completed.stdout)
            self.assertIn("7,9", completed.stdout)

    def test_status_defaults_to_query_latest_chain_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")
            state_path = tmp / "status_cache" / "latest_state.json"
            state_path.parent.mkdir()
            child_task_dir = tmp / "crab_sample_cfg__recover1"
            child_task_dir.mkdir()
            state_path.write_text(
                json.dumps(
                    {
                        "cwd": str(tmp),
                        "families": {
                            "crab_sample_cfg": {
                                "root_task_dir": "crab_sample_cfg",
                                "root_cfg": str(cfg_path),
                                "attempt_order": [
                                    "crab_sample_cfg",
                                    "crab_sample_cfg__recover1",
                                ],
                                "latest_attempt_id": "crab_sample_cfg__recover1",
                            }
                        },
                        "attempts": {
                            "crab_sample_cfg": {
                                "task_dir": "crab_sample_cfg",
                                "task_path": str(tmp / "crab_sample_cfg"),
                                "cfg": str(cfg_path),
                                "cfg_path": str(cfg_path),
                                "request_name": "sample_cfg",
                                "family_id": "crab_sample_cfg",
                                "parent_attempt_id": None,
                                "generation": 0,
                                "status": {"status_collection_state": "ok_json"},
                                "recovery": {},
                            },
                            "crab_sample_cfg__recover1": {
                                "task_dir": "crab_sample_cfg__recover1",
                                "task_path": str(child_task_dir),
                                "cfg": str(cfg_path),
                                "cfg_path": str(cfg_path),
                                "request_name": "sample_cfg__recover1",
                                "family_id": "crab_sample_cfg",
                                "parent_attempt_id": "crab_sample_cfg",
                                "generation": 1,
                                "status": {"status_collection_state": "ok_json"},
                                "recovery": {},
                            },
                        },
                    }
                )
            )

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "FAKE_CRAB_STATUS_OUTPUT": SAMPLE_STATUS_OUTPUT,
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                }
            )

            completed = self.run_command(
                [
                    "bash",
                    str(STATUS_SH),
                    "--manifest",
                    str(manifest_path),
                    "--cache-dir",
                    str(state_path.parent),
                ],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            crab_calls = crab_log.read_text()
            self.assertIn(f"status -d {child_task_dir} --json", crab_calls)
            self.assertNotIn(f"status -d {tmp / 'crab_sample_cfg'} --json", crab_calls)

    def test_status_skips_cached_completed_finished_tasks_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")
            state_path = tmp / "status_cache" / "latest_state.json"
            state_path.parent.mkdir()
            state_path.write_text(
                json.dumps(
                    {
                        "cwd": str(tmp),
                        "families": {
                            "crab_sample_cfg": {
                                "root_task_dir": "crab_sample_cfg",
                                "root_cfg": str(cfg_path),
                                "attempt_order": ["crab_sample_cfg"],
                                "latest_attempt_id": "crab_sample_cfg",
                            }
                        },
                        "attempts": {
                            "crab_sample_cfg": {
                                "task_dir": "crab_sample_cfg",
                                "task_path": str(tmp / "crab_sample_cfg"),
                                "cfg": str(cfg_path),
                                "cfg_path": str(cfg_path),
                                "request_name": "sample_cfg",
                                "family_id": "crab_sample_cfg",
                                "generation": 0,
                                "status": {
                                    "status_collection_state": "ok_json",
                                    "server_status": "SUBMITTED",
                                    "scheduler_status": "COMPLETED",
                                    "job_count": 3,
                                    "job_states": {"finished": 3},
                                    "failed_job_count": 0,
                                    "failed_job_ids": [],
                                },
                                "recovery": {},
                            }
                        },
                    }
                )
            )

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "FAKE_CRAB_STATUS_OUTPUT": SAMPLE_STATUS_OUTPUT,
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                }
            )

            completed = self.run_command(
                [
                    "bash",
                    str(STATUS_SH),
                    "--manifest",
                    str(manifest_path),
                    "--cache-dir",
                    str(state_path.parent),
                ],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("note=cached-terminal-skip", completed.stdout)
            self.assertFalse(crab_log.exists())

    def test_status_skips_cached_killed_tasks_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")
            state_path = tmp / "status_cache" / "latest_state.json"
            state_path.parent.mkdir()
            state_path.write_text(
                json.dumps(
                    {
                        "cwd": str(tmp),
                        "families": {
                            "crab_sample_cfg": {
                                "root_task_dir": "crab_sample_cfg",
                                "root_cfg": str(cfg_path),
                                "attempt_order": ["crab_sample_cfg"],
                                "latest_attempt_id": "crab_sample_cfg",
                            }
                        },
                        "attempts": {
                            "crab_sample_cfg": {
                                "task_dir": "crab_sample_cfg",
                                "task_path": str(tmp / "crab_sample_cfg"),
                                "cfg": str(cfg_path),
                                "cfg_path": str(cfg_path),
                                "request_name": "sample_cfg",
                                "family_id": "crab_sample_cfg",
                                "generation": 0,
                                "status": {
                                    "status_collection_state": "header_only_killed",
                                    "server_status": "KILLED",
                                    "scheduler_status": "FAILED (KILLED)",
                                    "job_count": 0,
                                    "job_states": {},
                                    "failed_job_count": 0,
                                    "failed_job_ids": [],
                                },
                                "recovery": {},
                            }
                        },
                    }
                )
            )

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "FAKE_CRAB_STATUS_OUTPUT": SAMPLE_STATUS_OUTPUT,
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                }
            )

            completed = self.run_command(
                [
                    "bash",
                    str(STATUS_SH),
                    "--manifest",
                    str(manifest_path),
                    "--cache-dir",
                    str(state_path.parent),
                ],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn("note=cached-terminal-skip", completed.stdout)
            self.assertFalse(crab_log.exists())

    def test_status_refresh_terminal_statuses_forces_live_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")
            task_dir = tmp / "crab_sample_cfg"
            task_dir.mkdir()
            state_path = tmp / "status_cache" / "latest_state.json"
            state_path.parent.mkdir()
            state_path.write_text(
                json.dumps(
                    {
                        "cwd": str(tmp),
                        "families": {
                            "crab_sample_cfg": {
                                "root_task_dir": "crab_sample_cfg",
                                "root_cfg": str(cfg_path),
                                "attempt_order": ["crab_sample_cfg"],
                                "latest_attempt_id": "crab_sample_cfg",
                            }
                        },
                        "attempts": {
                            "crab_sample_cfg": {
                                "task_dir": "crab_sample_cfg",
                                "task_path": str(task_dir),
                                "cfg": str(cfg_path),
                                "cfg_path": str(cfg_path),
                                "request_name": "sample_cfg",
                                "family_id": "crab_sample_cfg",
                                "generation": 0,
                                "status": {
                                    "status_collection_state": "ok_json",
                                    "server_status": "SUBMITTED",
                                    "scheduler_status": "COMPLETED",
                                    "job_count": 3,
                                    "job_states": {"finished": 3},
                                    "failed_job_count": 0,
                                    "failed_job_ids": [],
                                },
                                "recovery": {},
                            }
                        },
                    }
                )
            )

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "FAKE_CRAB_STATUS_OUTPUT": SAMPLE_STATUS_OUTPUT,
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                }
            )

            completed = self.run_command(
                [
                    "bash",
                    str(STATUS_SH),
                    "--manifest",
                    str(manifest_path),
                    "--cache-dir",
                    str(state_path.parent),
                    "--refresh-terminal-statuses",
                ],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertTrue(crab_log.exists())
            self.assertIn(f"status -d {task_dir} --json", crab_log.read_text())

    def test_python_help_keeps_status_available_but_recovery_builder_needs_cmsenv(self) -> None:
        env = self.base_env()
        status_help = self.run_command(
            [sys.executable, str(STATUS_SNAPSHOT_PY), "collect", "--help"], env=env
        )
        self.assertEqual(status_help.returncode, 0)
        self.assertIn("Output files:", status_help.stdout)
        self.assertIn("--cache-dir", status_help.stdout)

        recovery_help = self.run_command(
            [sys.executable, str(RECOVERY_BUILDER_PY), "plan", "--help"], env=env
        )
        self.assertNotEqual(recovery_help.returncode, 0)
        self.assertIn("FWCore.PythonUtilities.LumiList", recovery_help.stderr)

        resubmit_help = self.run_command(
            [sys.executable, str(RESUBMIT_PY), "--help"], env=env
        )
        self.assertEqual(resubmit_help.returncode, 0)
        self.assertIn("--use-cached-status", resubmit_help.stdout)

    def test_kill_recover_dry_run_reports_before_kill_for_normal_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")
            recovery_cache_dir = tmp / "recovery_cache"
            recovery_cache_dir.mkdir()
            status_cache_dir = tmp / "status_cache"
            status_cache_dir.mkdir()
            task_path = tmp / "crab_sample_cfg"
            state_path = status_cache_dir / "latest_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "families": {
                            "crab_sample_cfg": {
                                "root_task_dir": "crab_sample_cfg",
                                "root_cfg": str(cfg_path),
                                "attempt_order": ["crab_sample_cfg"],
                                "latest_attempt_id": "crab_sample_cfg",
                            }
                        },
                        "attempts": {
                            "crab_sample_cfg": {
                                "task_dir": "crab_sample_cfg",
                                "task_path": str(task_path),
                                "cfg": str(cfg_path),
                                "cfg_path": str(cfg_path),
                                "request_name": "sample_cfg",
                                "family_id": "crab_sample_cfg",
                                "generation": 0,
                                "planned_lumi_mask": ROOT_COMPACT_MASK,
                                "original_lumi_mask": ROOT_COMPACT_MASK,
                                "status_revision": "sha256:test",
                                "status": {"status_collection_state": "ok_json", "job_states": {"idle": 1}, "jobs": {}},
                                "recovery": {
                                    "classification": "recovery_candidate",
                                    "derived_from_revision": "sha256:test",
                                    "executable": True,
                                    "has_child_attempt": False,
                                },
                                "artifacts": {
                                    "report_dir": str(recovery_cache_dir / "reports" / "crab_sample_cfg"),
                                    "preserved_not_finished_lumis": str(
                                        recovery_cache_dir / "reports" / "crab_sample_cfg" / "notFinishedLumis.json"
                                    ),
                                    "next_recover_cfg": str(recovery_cache_dir / "configs" / "sample__recover1.py"),
                                    "next_planned_lumi_mask_file": str(
                                        recovery_cache_dir / "lumimasks" / "sample__recover1.json"
                                    ),
                                },
                            }
                        },
                    }
                )
            )

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                }
            )

            completed = self.run_command(
                [
                    "bash",
                    str(KILL_RECOVER_SH),
                    "--dry-run",
                    "--use-prepared-plan",
                    "--manifest",
                    str(manifest_path),
                    "--status-cache-dir",
                    str(status_cache_dir),
                    "--recovery-cache-dir",
                    str(recovery_cache_dir),
                ],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            lines = [line for line in completed.stdout.splitlines() if line.startswith("[")]
            self.assertGreaterEqual(len(lines), 6)
            self.assertIn("crab report -d", lines[0])
            self.assertIn("cp -f", lines[1])
            self.assertIn("crab kill -d", lines[2])

    def test_kill_recover_dry_run_reports_first_for_killed_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# config\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")
            recovery_cache_dir = tmp / "recovery_cache"
            recovery_cache_dir.mkdir()
            status_cache_dir = tmp / "status_cache"
            status_cache_dir.mkdir()
            task_path = tmp / "crab_sample_cfg"
            state_path = status_cache_dir / "latest_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "families": {
                            "crab_sample_cfg": {
                                "root_task_dir": "crab_sample_cfg",
                                "root_cfg": str(cfg_path),
                                "attempt_order": ["crab_sample_cfg"],
                                "latest_attempt_id": "crab_sample_cfg",
                            }
                        },
                        "attempts": {
                            "crab_sample_cfg": {
                                "task_dir": "crab_sample_cfg",
                                "task_path": str(task_path),
                                "cfg": str(cfg_path),
                                "cfg_path": str(cfg_path),
                                "request_name": "sample_cfg",
                                "family_id": "crab_sample_cfg",
                                "generation": 0,
                                "planned_lumi_mask": ROOT_COMPACT_MASK,
                                "original_lumi_mask": ROOT_COMPACT_MASK,
                                "status_revision": "sha256:test",
                                "status": {"status_collection_state": "ok_json", "job_states": {"idle": 1}, "jobs": {}},
                                "recovery": {
                                    "classification": "killed_recovery_candidate",
                                    "derived_from_revision": "sha256:test",
                                    "executable": True,
                                    "has_child_attempt": False,
                                },
                                "artifacts": {
                                    "report_dir": str(recovery_cache_dir / "reports" / "crab_sample_cfg"),
                                    "preserved_not_finished_lumis": str(
                                        recovery_cache_dir / "reports" / "crab_sample_cfg" / "notFinishedLumis.json"
                                    ),
                                    "next_recover_cfg": str(recovery_cache_dir / "configs" / "sample__recover1.py"),
                                    "next_planned_lumi_mask_file": str(
                                        recovery_cache_dir / "lumimasks" / "sample__recover1.json"
                                    ),
                                },
                            }
                        },
                    }
                )
            )

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                }
            )

            completed = self.run_command(
                [
                    "bash",
                    str(KILL_RECOVER_SH),
                    "--dry-run",
                    "--use-prepared-plan",
                    "--manifest",
                    str(manifest_path),
                    "--status-cache-dir",
                    str(status_cache_dir),
                    "--recovery-cache-dir",
                    str(recovery_cache_dir),
                ],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            lines = [line for line in completed.stdout.splitlines() if line.startswith("[")]
            self.assertGreaterEqual(len(lines), 5)
            self.assertIn("crab report -d", lines[0])
            self.assertIn("preserve-if-present", completed.stdout)
            self.assertNotIn("crab kill -d", completed.stdout)

    def test_kill_recover_execute_falls_back_to_original_mask_when_report_has_no_not_finished_and_no_jobs_finished(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            manifest_path = tmp / "manifest.txt"
            recovery_cache_dir = tmp / "recovery_cache"
            recovery_cache_dir.mkdir()
            status_cache_dir = tmp / "status_cache"
            cfg_path, task_path, state_path = make_recovery_state(
                tmp,
                status_cache_dir,
                recovery_cache_dir,
                classification="recovery_candidate",
                job_states={"idle": 565},
            )
            manifest_path.write_text(f"{cfg_path}\n")

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "PYTHONPATH": f"{tmp}:{env.get('PYTHONPATH', '')}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "FAKE_CRAB_STATUS_OUTPUT": "Status on the CRAB server:\tSUBMITTED\n",
                    "FAKE_CRAB_REPORT_MODE": "no_not_finished",
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                }
            )

            completed = self.run_command(
                [
                    "bash",
                    str(KILL_RECOVER_SH),
                    "--execute",
                    "--use-prepared-plan",
                    "--manifest",
                    str(manifest_path),
                    "--status-cache-dir",
                    str(status_cache_dir),
                    "--recovery-cache-dir",
                    str(recovery_cache_dir),
                ],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            self.assertIn(
                "No fresh notFinishedLumis.json produced",
                completed.stderr,
            )

            crab_commands = crab_log.read_text()
            self.assertIn(f"status -d {task_path}", crab_commands)
            self.assertIn(f"report -d {task_path}", crab_commands)
            self.assertIn(f"kill -d {task_path}", crab_commands)
            self.assertIn(
                f"submit -c {recovery_cache_dir / 'configs' / 'sample_cfg__recover1.py'}",
                crab_commands,
            )

            state = json.loads(state_path.read_text())
            task = state["attempts"]["crab_sample_cfg"]
            self.assertEqual(task["recovery"]["resolved_lumi_source"], "parent_planned_lumi_mask_no_finished_jobs")
            self.assertEqual(task["recovery"]["resolved_lumi_mask"], ROOT_COMPACT_MASK)

    def test_kill_recover_execute_runs_report_but_skips_kill_when_runtime_status_is_killed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            proxy_path, crab_log = make_fake_tools(tmp)
            manifest_path = tmp / "manifest.txt"
            recovery_cache_dir = tmp / "recovery_cache"
            recovery_cache_dir.mkdir()
            status_cache_dir = tmp / "status_cache"
            cfg_path, task_path, state_path = make_recovery_state(
                tmp,
                status_cache_dir,
                recovery_cache_dir,
                classification="recovery_candidate",
                job_states={"idle": 565},
            )
            manifest_path.write_text(f"{cfg_path}\n")

            env = self.base_env()
            env.update(
                {
                    "PATH": f"{tmp / 'bin'}:{env['PATH']}",
                    "PYTHONPATH": f"{tmp}:{env.get('PYTHONPATH', '')}",
                    "X509_USER_PROXY": str(proxy_path),
                    "FAKE_PROXY_PATH": str(proxy_path),
                    "FAKE_CRAB_LOG": str(crab_log),
                    "FAKE_CRAB_STATUS_OUTPUT": "Status on the CRAB server:\tKILLED\n",
                    "CMSSW_BASE": "/tmp/cmssw",
                    "CMSSW_RELEASE_BASE": "/tmp/cmssw_release",
                    "SCRAM_ARCH": "el9_amd64_gcc13",
                }
            )

            completed = self.run_command(
                [
                    "bash",
                    str(KILL_RECOVER_SH),
                    "--execute",
                    "--use-prepared-plan",
                    "--manifest",
                    str(manifest_path),
                    "--status-cache-dir",
                    str(status_cache_dir),
                    "--recovery-cache-dir",
                    str(recovery_cache_dir),
                ],
                env=env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)

            crab_commands = crab_log.read_text()
            self.assertIn(f"status -d {task_path}", crab_commands)
            self.assertIn(f"report -d {task_path}", crab_commands)
            self.assertNotIn(f"kill -d {task_path}", crab_commands)
            self.assertIn(
                f"submit -c {recovery_cache_dir / 'configs' / 'sample_cfg__recover1.py'}",
                crab_commands,
            )

            state = json.loads(state_path.read_text())
            task = state["attempts"]["crab_sample_cfg"]
            self.assertEqual(task["recovery"]["resolved_lumi_source"], "parent_planned_lumi_mask_killed")
            self.assertEqual(task["recovery"]["resolved_lumi_mask"], ROOT_COMPACT_MASK)


if __name__ == "__main__":
    unittest.main()
