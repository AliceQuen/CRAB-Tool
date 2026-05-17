#!/usr/bin/env python3
"""Unit tests for crab_status_snapshot.py."""

from __future__ import annotations

import json
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("crab_status_snapshot.py")
MODULE_SPEC = importlib.util.spec_from_file_location("crab_status_snapshot", MODULE_PATH)
snapshot = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(snapshot)


SAMPLE_STATUS_OUTPUT = """Rucio client intialized for account chiw
CRAB project directory:\t\t/path/to/crab_task
Task name:\t\t\t260411_080042:chiw_crab_task
Status on the CRAB server:\tSUBMITTED
Status on the scheduler:\tSUBMITTED

{"1": {"State": "finished", "Error": [0, "OK", {}], "JobIds": ["144836102.0"]}, "2": {"State": "failed", "Error": [8020, "File open error", {}], "JobIds": ["144836103.0"]}, "3": {"State": "transferring", "Error": [0, "OK", {}], "JobIds": ["144836104.0"]}}
Log file is /path/to/crab.log
"""

KILLED_STATUS_OUTPUT = """Rucio client intialized for account chiw
CRAB project directory:\t\t/path/to/crab_task
Task name:\t\t\t260411_080042:chiw_crab_task
Status on the CRAB server:\tKILLED

Log file is /path/to/crab.log
"""


class CrabStatusSnapshotTest(unittest.TestCase):
    def test_extract_status_payload_ignores_text_wrapper(self) -> None:
        payload = snapshot.extract_status_payload(SAMPLE_STATUS_OUTPUT)
        self.assertEqual(sorted(payload), ["1", "2", "3"])
        self.assertEqual(payload["2"]["State"], "failed")

    def test_summarize_jobs_tracks_failed_job_ids(self) -> None:
        payload = snapshot.extract_status_payload(SAMPLE_STATUS_OUTPUT)
        job_states, failed_job_ids = snapshot.summarize_jobs(payload)
        self.assertEqual(
            job_states, {"failed": 1, "finished": 1, "transferring": 1}
        )
        self.assertEqual(failed_job_ids, ["2"])

    def test_list_failed_rejects_query_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "latest_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "query_failures": ["crab_task_a"],
                        "families": {
                            "crab_task_a": {
                                "root_task_dir": "crab_task_a",
                                "attempt_order": ["crab_task_a"],
                                "latest_attempt_id": "crab_task_a",
                            }
                        },
                        "attempts": {
                            "crab_task_a": {
                                "task_dir": "crab_task_a",
                                "status": {
                                    "failed_job_ids": ["7"],
                                    "failed_job_count": 1,
                                },
                            }
                        },
                    }
                )
            )
            args = type("Args", (), {"state_file": str(state_path), "summary_file": None})
            self.assertEqual(snapshot.run_list_failed(args), 1)

    def test_list_failed_reads_failed_jobs_from_state_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "latest_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "query_failures": [],
                        "attempts": {
                            "crab_task": {
                                "task_dir": "crab_task",
                                "status": {
                                    "failed_job_ids": ["7", "9"],
                                    "failed_job_count": 2,
                                },
                            }
                        },
                    }
                )
            )
            args = type("Args", (), {"state_file": str(state_path), "summary_file": None})
            with tempfile.TemporaryDirectory() as _:
                self.assertEqual(snapshot.run_list_failed(args), 0)

    def test_list_failed_only_emits_latest_chain_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "latest_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "query_failures": ["crab_task"],
                        "families": {
                            "crab_task": {
                                "root_task_dir": "crab_task",
                                "attempt_order": ["crab_task", "crab_task__recover1"],
                                "latest_attempt_id": "crab_task__recover1",
                            }
                        },
                        "attempts": {
                            "crab_task": {
                                "task_dir": "crab_task",
                                "status": {
                                    "failed_job_ids": ["3"],
                                    "failed_job_count": 1,
                                },
                            },
                            "crab_task__recover1": {
                                "task_dir": "crab_task__recover1",
                                "status": {
                                    "failed_job_ids": ["7", "9"],
                                    "failed_job_count": 2,
                                },
                            },
                        },
                    }
                )
            )
            args = type("Args", (), {"state_file": str(state_path), "summary_file": None})
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(snapshot.run_list_failed(args), 0)
            self.assertEqual(stdout.getvalue().strip(), "crab_task__recover1\t7,9\t2")

    def test_iter_latest_failed_entries_skips_killed_and_holding_tasks(self) -> None:
        state = snapshot.ensure_state_shape(
            {
                "families": {
                    "crab_a": {
                        "root_task_dir": "crab_a",
                        "attempt_order": ["crab_a"],
                        "latest_attempt_id": "crab_a",
                    },
                    "crab_b": {
                        "root_task_dir": "crab_b",
                        "attempt_order": ["crab_b"],
                        "latest_attempt_id": "crab_b",
                    },
                    "crab_c": {
                        "root_task_dir": "crab_c",
                        "attempt_order": ["crab_c"],
                        "latest_attempt_id": "crab_c",
                    },
                },
                "attempts": {
                    "crab_a": {
                        "task_dir": "crab_a",
                        "status": {
                            "server_status": "SUBMITTED",
                            "failed_job_ids": ["3", "5"],
                            "failed_job_count": 2,
                        },
                    },
                    "crab_b": {
                        "task_dir": "crab_b",
                        "status": {
                            "server_status": "KILLED",
                            "failed_job_ids": ["7"],
                            "failed_job_count": 1,
                        },
                    },
                    "crab_c": {
                        "task_dir": "crab_c",
                        "status": {
                            "server_status": "HOLDING on command RESUBMIT",
                            "failed_job_ids": ["9"],
                            "failed_job_count": 1,
                        },
                    },
                },
            }
        )
        self.assertEqual(snapshot.iter_latest_failed_entries(state), [("crab_a", ["3", "5"], 2)])

    def test_terminal_status_helpers_identify_completed_and_killed_cache_entries(self) -> None:
        self.assertTrue(
            snapshot.is_cached_completed_and_all_finished(
                {
                    "status_collection_state": snapshot.STATUS_COLLECTION_OK,
                    "scheduler_status": "COMPLETED",
                    "job_count": 4,
                    "job_states": {"finished": 4},
                    "failed_job_count": 0,
                }
            )
        )
        self.assertFalse(
            snapshot.is_cached_completed_and_all_finished(
                {
                    "status_collection_state": snapshot.STATUS_COLLECTION_OK,
                    "scheduler_status": "COMPLETED",
                    "job_count": 4,
                    "job_states": {"finished": 3, "running": 1},
                    "failed_job_count": 0,
                }
            )
        )
        self.assertTrue(
            snapshot.is_cached_killed(
                {
                    "status_collection_state": snapshot.STATUS_COLLECTION_HEADER_ONLY_KILLED,
                    "server_status": "KILLED",
                }
            )
        )
        self.assertFalse(
            snapshot.is_cached_killed(
                {
                    "status_collection_state": snapshot.STATUS_COLLECTION_FATAL_ERROR,
                    "server_status": "KILLED",
                }
            )
        )

    def test_build_task_summary_treats_killed_without_json_as_header_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "crab_task"
            task_dir.mkdir()
            original_query = snapshot.query_task_status
            try:
                snapshot.query_task_status = lambda *_args, **_kwargs: (
                    subprocess.CompletedProcess(
                        args=["crab", "status"],
                        returncode=0,
                        stdout=KILLED_STATUS_OUTPUT,
                        stderr="",
                    ),
                    ["crab", "status", "-d", str(task_dir), "--json"],
                )
                summary, payload, stdout, stderr, cmd = snapshot.build_task_summary(
                    "sample.py", task_dir, []
                )
            finally:
                snapshot.query_task_status = original_query

            self.assertIsNone(payload)
            self.assertEqual(stdout, KILLED_STATUS_OUTPUT)
            self.assertEqual(stderr, "")
            self.assertIn("--json", cmd)
            self.assertEqual(
                summary["status_collection_state"],
                snapshot.STATUS_COLLECTION_HEADER_ONLY_KILLED,
            )
            self.assertIsNone(summary["query_error"])
            self.assertIn("Failed to parse status JSON", summary["query_warning"])

    def test_task_dir_from_cfg_uses_task_root_even_for_absolute_cfg(self) -> None:
        task_root = Path("/tmp/work")
        cfg = "/tmp/somewhere/configs/sample.py"
        self.assertEqual(
            snapshot.task_dir_from_cfg(task_root, cfg),
            task_root / "crab_sample",
        )

    def test_merge_attempt_status_clears_stale_resolved_lumi_mask(self) -> None:
        summary, payload, *_rest = (
            {
                "cfg": "sample.py",
                "task_dir": "crab_sample",
                "task_path": "/tmp/crab_sample",
                "task_name": "task",
                "server_status": "SUBMITTED",
                "scheduler_status": "SUBMITTED",
                "dashboard_url": None,
                "job_count": 1,
                "job_states": {"finished": 1},
                "failed_job_count": 0,
                "failed_job_ids": [],
                "status_collection_state": snapshot.STATUS_COLLECTION_OK,
                "query_error": None,
                "query_warning": None,
            },
            {"1": {"State": "finished"}},
            "",
            "",
            [],
        )
        status = snapshot.make_status_payload(summary, payload)
        attempt = snapshot.merge_attempt_status(
            {
                "request_name": "sample",
                "recovery": {
                    "derived_from_revision": "sha256:stale",
                    "resolved_lumi_action": "submit",
                    "resolved_lumi_source": "preserved_not_finished",
                    "resolved_lumi_mask": "/tmp/chiw/mask.json",
                },
            },
            "sample.py",
            Path("/tmp/crab_sample"),
            status,
        )
        self.assertIsNone(attempt["recovery"]["resolved_lumi_mask"])

    def test_merge_attempt_status_preserves_hold_since_while_holding(self) -> None:
        status = snapshot.make_status_payload(
            {
                "cfg": "sample.py",
                "task_dir": "crab_sample",
                "task_path": "/tmp/crab_sample",
                "task_name": "task",
                "server_status": "HOLDING on command RESUBMIT",
                "scheduler_status": "FAILED",
                "dashboard_url": None,
                "job_count": 1,
                "job_states": {"failed": 1},
                "failed_job_count": 1,
                "failed_job_ids": ["1"],
                "status_collection_state": snapshot.STATUS_COLLECTION_OK,
                "query_error": None,
                "query_warning": None,
            },
            {"1": {"State": "failed"}},
        )
        attempt = snapshot.merge_attempt_status(
            {
                "request_name": "sample",
                "status": {
                    "server_status": "HOLDING on command RESUBMIT",
                    "hold_since": "2026-04-22T15:30:12+00:00",
                },
            },
            "sample.py",
            Path("/tmp/crab_sample"),
            status,
        )
        self.assertEqual(attempt["status"]["hold_since"], "2026-04-22T15:30:12+00:00")

    def test_merge_attempt_status_uses_previous_collected_at_for_legacy_holding(self) -> None:
        status = snapshot.make_status_payload(
            {
                "cfg": "sample.py",
                "task_dir": "crab_sample",
                "task_path": "/tmp/crab_sample",
                "task_name": "task",
                "server_status": "HOLDING on command RESUBMIT",
                "scheduler_status": "FAILED",
                "dashboard_url": None,
                "job_count": 1,
                "job_states": {"failed": 1},
                "failed_job_count": 1,
                "failed_job_ids": ["1"],
                "status_collection_state": snapshot.STATUS_COLLECTION_OK,
                "query_error": None,
                "query_warning": None,
            },
            {"1": {"State": "failed"}},
        )
        attempt = snapshot.merge_attempt_status(
            {
                "request_name": "sample",
                "status": {
                    "server_status": "HOLDING on command RESUBMIT",
                    "collected_at": "2026-04-22T15:30:12+00:00",
                },
            },
            "sample.py",
            Path("/tmp/crab_sample"),
            status,
        )
        self.assertEqual(attempt["status"]["hold_since"], "2026-04-22T15:30:12+00:00")

    def test_run_query_latest_skips_cached_terminal_attempts_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# cfg\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")
            state_path = tmp / "latest_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "cwd": str(tmp),
                        "families": {
                            "crab_sample_cfg": {
                                "root_task_dir": "crab_sample_cfg",
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
                                "status": {
                                    "status_collection_state": snapshot.STATUS_COLLECTION_OK,
                                    "scheduler_status": "COMPLETED",
                                    "server_status": "SUBMITTED",
                                    "job_count": 3,
                                    "job_states": {"finished": 3},
                                    "failed_job_count": 0,
                                    "failed_job_ids": [],
                                },
                            }
                        },
                    }
                )
            )

            args = type(
                "Args",
                (),
                {
                    "manifest": str(manifest_path),
                    "cache_dir": str(tmp),
                    "state_file": str(state_path),
                    "no_update_cache": False,
                    "raw_output": False,
                    "refresh_terminal_statuses": False,
                },
            )()
            stdout = io.StringIO()
            original_cwd = Path.cwd()
            original_query = snapshot.query_task_status
            try:
                os.chdir(tmp)

                def fail_query(*_args, **_kwargs):
                    raise AssertionError("query_task_status should not be called")

                snapshot.query_task_status = fail_query
                with redirect_stdout(stdout):
                    self.assertEqual(snapshot.run_query_latest(args, []), 0)
            finally:
                snapshot.query_task_status = original_query
                os.chdir(original_cwd)

            self.assertIn("note=cached-terminal-skip", stdout.getvalue())

    def test_run_query_latest_refresh_terminal_statuses_overrides_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# cfg\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n")
            task_dir = tmp / "crab_sample_cfg"
            task_dir.mkdir()
            state_path = tmp / "latest_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "cwd": str(tmp),
                        "families": {
                            "crab_sample_cfg": {
                                "root_task_dir": "crab_sample_cfg",
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
                                "status": {
                                    "status_collection_state": snapshot.STATUS_COLLECTION_OK,
                                    "scheduler_status": "COMPLETED",
                                    "server_status": "SUBMITTED",
                                    "job_count": 3,
                                    "job_states": {"finished": 3},
                                    "failed_job_count": 0,
                                    "failed_job_ids": [],
                                },
                            }
                        },
                    }
                )
            )

            args = type(
                "Args",
                (),
                {
                    "manifest": str(manifest_path),
                    "cache_dir": str(tmp),
                    "state_file": str(state_path),
                    "no_update_cache": False,
                    "raw_output": False,
                    "refresh_terminal_statuses": True,
                },
            )()
            query_calls: list[str] = []
            original_cwd = Path.cwd()
            original_query = snapshot.query_task_status
            try:
                os.chdir(tmp)

                def fake_query(task_path: Path, extra_args: list[str]):
                    query_calls.append(str(task_path))
                    return (
                        subprocess.CompletedProcess(
                            args=["crab", "status"],
                            returncode=0,
                            stdout=SAMPLE_STATUS_OUTPUT,
                            stderr="",
                        ),
                        ["crab", "status", "-d", str(task_path), "--json", *extra_args],
                    )

                snapshot.query_task_status = fake_query
                self.assertEqual(snapshot.run_query_latest(args, []), 0)
            finally:
                snapshot.query_task_status = original_query
                os.chdir(original_cwd)

            self.assertEqual(query_calls, [str(task_dir)])

    def test_run_collect_skips_cached_terminal_tracked_tasks_but_queries_new_manifest_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "sample_cfg.py"
            cfg_path.write_text("# cfg\n")
            new_cfg_path = tmp / "new_cfg.py"
            new_cfg_path.write_text("# cfg\n")
            manifest_path = tmp / "manifest.txt"
            manifest_path.write_text(f"{cfg_path}\n{new_cfg_path}\n")
            new_task_dir = tmp / "crab_new_cfg"
            new_task_dir.mkdir()
            state_path = tmp / "latest_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "cwd": str(tmp),
                        "attempts": {
                            "crab_sample_cfg": {
                                "task_dir": "crab_sample_cfg",
                                "task_path": str(tmp / "crab_sample_cfg"),
                                "cfg": str(cfg_path),
                                "cfg_path": str(cfg_path),
                                "status": {
                                    "status_collection_state": snapshot.STATUS_COLLECTION_HEADER_ONLY_KILLED,
                                    "server_status": "KILLED",
                                    "scheduler_status": "FAILED (KILLED)",
                                    "job_count": 0,
                                    "job_states": {},
                                    "failed_job_count": 0,
                                    "failed_job_ids": [],
                                },
                            }
                        },
                    }
                )
            )

            args = type(
                "Args",
                (),
                {
                    "manifest": str(manifest_path),
                    "cache_dir": str(tmp),
                    "state_file": str(state_path),
                    "refresh_terminal_statuses": False,
                },
            )()
            query_calls: list[str] = []
            original_cwd = Path.cwd()
            original_query = snapshot.query_task_status
            try:
                os.chdir(tmp)

                def fake_query(task_path: Path, extra_args: list[str]):
                    query_calls.append(str(task_path))
                    return (
                        subprocess.CompletedProcess(
                            args=["crab", "status"],
                            returncode=0,
                            stdout=SAMPLE_STATUS_OUTPUT,
                            stderr="",
                        ),
                        ["crab", "status", "-d", str(task_path), "--json", *extra_args],
                    )

                snapshot.query_task_status = fake_query
                self.assertEqual(snapshot.run_collect(args, []), 0)
            finally:
                snapshot.query_task_status = original_query
                os.chdir(original_cwd)

            self.assertEqual(query_calls, [str(new_task_dir)])
            state = snapshot.ensure_state_shape(snapshot.load_json(state_path))
            self.assertEqual(state["header_only_killed_tasks"], ["crab_sample_cfg"])


if __name__ == "__main__":
    unittest.main()
