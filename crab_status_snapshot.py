#!/usr/bin/env python3
"""Collect machine-readable CRAB status into one authoritative state file."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from crab_recovery_chain import get_latest_task, rebuild_chain_index

INCOMPATIBLE_STATUS_ARGS = {
    "--jobids",
    "--long",
    "--sort",
    "--summary",
    "--verboseErrors",
}
STATE_NAME = "latest_state.json"
SCHEMA_VERSION = 2
RECOVERY_SUFFIX = "recover"
STATUS_COLLECTION_OK = "ok_json"
STATUS_COLLECTION_HEADER_ONLY_KILLED = "header_only_killed"
STATUS_COLLECTION_FATAL_ERROR = "fatal_error"
STATUS_COLLECTION_NOT_COLLECTED = "not_collected"


class HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter
):
    """Help formatter with defaults and preserved line breaks."""


def ensure_cmssw_env() -> None:
    required = ("CMSSW_BASE", "CMSSW_RELEASE_BASE", "SCRAM_ARCH")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        missing_names = ", ".join(missing)
        raise RuntimeError(
            "CMSSW environment is not active. "
            f"Missing {missing_names}. Run 'cmsenv' first."
        )


def ensure_proxy_env() -> None:
    proxy_path = os.environ.get("X509_USER_PROXY")
    if not proxy_path:
        raise RuntimeError("export X509_USER_PROXY=$(voms-proxy-info -path) first")
    if not Path(proxy_path).is_file():
        raise RuntimeError(f"Missing proxy file {proxy_path}.")
    completed = subprocess.run(
        ["voms-proxy-info", "-file", proxy_path, "-all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "proxy validation failed"
        raise RuntimeError(message)


def add_manifest_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--manifest",
        default="generated_crab_configs.txt",
        help="Manifest that lists one CRAB config path per line.",
    )


def add_cache_locator_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cache-dir",
        default="status_cache",
        help="Directory where the authoritative latest_state.json file is written.",
    )
    parser.add_argument(
        "--state-file",
        default=None,
        help="Explicit path for the authoritative state JSON file.",
    )


def add_state_reader_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state-file",
        default=f"status_cache/{STATE_NAME}",
        help="Authoritative state file produced by a status query command.",
    )
    parser.add_argument(
        "--summary-file",
        default=None,
        help="Deprecated alias for --state-file.",
    )


def add_terminal_refresh_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--refresh-terminal-statuses",
        action="store_true",
        help=(
            "Force live status refresh even when cached status is already terminal "
            "(killed or completed with all jobs finished)."
        ),
    )


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description="Collect, query, display, and summarize CRAB status snapshots.",
        formatter_class=HelpFormatter,
        epilog=(
            "Examples:\n"
            "  crab_status_snapshot.py collect --cache-dir status_cache\n"
            "  crab_status_snapshot.py query-latest --cache-dir status_cache\n"
            "  crab_status_snapshot.py query-all --no-update-cache --raw-output -- --verboseErrors\n"
            "  crab_status_snapshot.py display-cache --state-file status_cache/latest_state.json\n"
            "  crab_status_snapshot.py collect --state-file status_cache/latest_state.json -- --instance prod\n"
            "  crab_status_snapshot.py list-failed --state-file status_cache/latest_state.json\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser(
        "collect",
        help="Query crab status for all tracked tasks and save one state file.",
        description=(
            "Query 'crab status --json' for every root task in the manifest plus any "
            "already-recorded recovery attempts, then update one authoritative state file."
        ),
        formatter_class=HelpFormatter,
        epilog=(
            "Output files:\n"
            "  <cache-dir>/latest_state.json\n\n"
            "Extra arguments after '--' are forwarded to 'crab status --json'.\n"
            "Do not combine machine-readable mode with --long, --summary, --sort,\n"
            "--verboseErrors, or --jobids."
        ),
    )
    add_manifest_arg(collect_parser)
    add_cache_locator_args(collect_parser)
    add_terminal_refresh_arg(collect_parser)

    query_all_parser = subparsers.add_parser(
        "query-all",
        help="Query all tracked tasks, with optional no-cache live mode.",
        description=(
            "By default this behaves like 'collect'. Use --no-update-cache to run "
            "live queries without rewriting latest_state.json."
        ),
        formatter_class=HelpFormatter,
    )
    add_manifest_arg(query_all_parser)
    add_cache_locator_args(query_all_parser)
    add_terminal_refresh_arg(query_all_parser)
    query_all_parser.add_argument(
        "--no-update-cache",
        action="store_true",
        help="Run live queries without updating latest_state.json.",
    )
    query_all_parser.add_argument(
        "--raw-output",
        action="store_true",
        help="Print raw `crab status` output. Allowed only with --no-update-cache.",
    )

    query_latest_parser = subparsers.add_parser(
        "query-latest",
        help="Query only the latest attempt in each recovery chain.",
        description=(
            "Refresh latest_state.json using only the end-of-chain attempt for each "
            "tracked family, plus manifest roots that are not yet tracked."
        ),
        formatter_class=HelpFormatter,
    )
    add_manifest_arg(query_latest_parser)
    add_cache_locator_args(query_latest_parser)
    add_terminal_refresh_arg(query_latest_parser)
    query_latest_parser.add_argument(
        "--no-update-cache",
        action="store_true",
        help="Run live queries without updating latest_state.json.",
    )
    query_latest_parser.add_argument(
        "--raw-output",
        action="store_true",
        help="Print raw `crab status` output. Allowed only with --no-update-cache.",
    )

    display_cache_parser = subparsers.add_parser(
        "display-cache",
        help="Show latest_state.json in a human-friendly chain summary.",
        formatter_class=HelpFormatter,
    )
    add_state_reader_args(display_cache_parser)

    list_failed_parser = subparsers.add_parser(
        "list-failed",
        help="List latest-attempt task directories that have failed jobs in the saved state file.",
        description=(
            "Read a saved latest_state.json file and print one tab-separated line for "
            "each latest chain attempt that currently contains failed CRAB jobs."
        ),
        formatter_class=HelpFormatter,
        epilog=(
            "Output columns:\n"
            "  task_dir<TAB>comma-separated job ids<TAB>failed job count"
        ),
    )
    add_state_reader_args(list_failed_parser)

    return parser.parse_known_args(argv)


def command_has_flag(args: list[str], flag: str) -> bool:
    return any(arg == flag or arg.startswith(f"{flag}=") for arg in args)


def ensure_compatible_status_args(extra_args: list[str]) -> None:
    for flag in INCOMPATIBLE_STATUS_ARGS:
        if command_has_flag(extra_args, flag):
            raise ValueError(
                f"{flag} is incompatible with machine-readable status collection. "
                "Use query-all/query-latest with --no-update-cache --raw-output for raw CRAB output."
            )


def read_manifest(manifest_path: Path) -> list[str]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest {manifest_path}. Run ./registerData.sh first.")
    return [line.strip() for line in manifest_path.read_text().splitlines() if line.strip()]


def resolve_state_file(args: argparse.Namespace) -> Path:
    if getattr(args, "summary_file", None):
        return Path(args.summary_file)
    if getattr(args, "state_file", None):
        return Path(args.state_file)
    return Path(args.cache_dir) / STATE_NAME


def task_dir_from_cfg(task_root: Path, cfg: str) -> Path:
    cfg_path = Path(cfg)
    task_name = f"crab_{cfg_path.stem}"
    return (task_root / task_name).resolve()


def extract_status_payload(stdout: str) -> dict[str, dict]:
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Could not locate JSON payload in `crab status --json` output.")
    return json.loads(stdout[start : end + 1])


def extract_header_value(stdout: str, label: str) -> str | None:
    prefix = f"{label}:"
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None


def summarize_jobs(payload: dict[str, dict]) -> tuple[dict[str, int], list[str]]:
    state_counts: collections.Counter[str] = collections.Counter()
    failed_job_ids: list[str] = []

    for crab_job_id, job in payload.items():
        state = str(job.get("State", "unknown"))
        state_counts[state] += 1
        if state == "failed":
            failed_job_ids.append(str(crab_job_id))

    failed_job_ids.sort(key=lambda value: int(value))
    return dict(sorted(state_counts.items())), failed_job_ids


def query_task_status(
    task_dir: Path, extra_args: list[str]
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    cmd = ["crab", "status", "-d", str(task_dir), "--json", *extra_args]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return completed, cmd


def query_task_status_raw(
    task_dir: Path, extra_args: list[str]
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    cmd = ["crab", "status", "-d", str(task_dir), *extra_args]
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return completed, cmd


def build_task_summary(
    cfg: str, task_dir: Path, extra_args: list[str]
) -> tuple[dict[str, Any], dict[str, dict] | None, str, str, list[str]]:
    summary: dict[str, Any] = {
        "cfg": cfg,
        "task_dir": task_dir.name,
        "task_path": str(task_dir),
        "task_name": None,
        "server_status": None,
        "scheduler_status": None,
        "dashboard_url": None,
        "job_count": 0,
        "job_states": {},
        "failed_job_count": 0,
        "failed_job_ids": [],
        "status_collection_state": STATUS_COLLECTION_OK,
        "query_error": None,
        "query_warning": None,
    }

    if not task_dir.is_dir():
        summary["status_collection_state"] = STATUS_COLLECTION_FATAL_ERROR
        summary["query_error"] = f"Missing CRAB task directory {task_dir.name}."
        return summary, None, "", "", []

    completed, cmd = query_task_status(task_dir, extra_args)
    stdout = completed.stdout
    stderr = completed.stderr

    summary["task_name"] = extract_header_value(stdout, "Task name")
    summary["server_status"] = extract_header_value(stdout, "Status on the CRAB server")
    summary["scheduler_status"] = extract_header_value(stdout, "Status on the scheduler")
    summary["dashboard_url"] = extract_header_value(stdout, "Dashboard monitoring URL")

    if completed.returncode != 0:
        summary["status_collection_state"] = STATUS_COLLECTION_FATAL_ERROR
        message = stderr.strip() or stdout.strip() or "unknown CRAB status failure"
        summary["query_error"] = (
            f"`{' '.join(cmd)}` failed with exit code {completed.returncode}: {message}"
        )
        return summary, None, stdout, stderr, cmd

    try:
        payload = extract_status_payload(stdout)
        job_states, failed_job_ids = summarize_jobs(payload)
    except Exception as exc:
        if summary["server_status"] == "KILLED":
            summary["status_collection_state"] = STATUS_COLLECTION_HEADER_ONLY_KILLED
            summary["query_warning"] = f"Failed to parse status JSON after kill: {exc}"
            return summary, None, stdout, stderr, cmd
        summary["status_collection_state"] = STATUS_COLLECTION_FATAL_ERROR
        summary["query_error"] = f"Failed to parse status JSON: {exc}"
        return summary, None, stdout, stderr, cmd

    summary["job_count"] = len(payload)
    summary["job_states"] = job_states
    summary["failed_job_count"] = len(failed_job_ids)
    summary["failed_job_ids"] = failed_job_ids
    return summary, payload, stdout, stderr, cmd


def format_task_summary(summary: dict[str, Any]) -> str:
    if summary["query_error"]:
        return f"{summary['task_dir']} query_error={summary['query_error']}"
    if summary["query_warning"]:
        return (
            f"{summary['task_dir']} "
            f"server={summary['server_status'] or 'unknown'} "
            f"warning={summary['query_warning']}"
        )
    states = " ".join(
        f"{state}={count}" for state, count in summary["job_states"].items()
    )
    return (
        f"{summary['task_dir']} "
        f"server={summary['server_status'] or 'unknown'} "
        f"scheduler={summary['scheduler_status'] or 'unknown'} "
        f"failed={summary['failed_job_count']} "
        f"{states}"
        f"{' ' + summary['summary_note'] if summary.get('summary_note') else ''}"
    ).strip()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp_path, path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_killed_server_status(server_status: str | None) -> bool:
    return (server_status or "").strip().upper() == "KILLED"


def is_holding_resubmit_server_status(server_status: str | None) -> bool:
    return (server_status or "").strip().upper().startswith(
        "HOLDING ON COMMAND RESUBMIT"
    )


def is_resubmit_eligible_status(status: dict[str, Any]) -> bool:
    server_status = status.get("server_status")
    return not is_killed_server_status(server_status) and not is_holding_resubmit_server_status(
        server_status
    )


def is_cached_completed_and_all_finished(status: dict[str, Any]) -> bool:
    if str(status.get("status_collection_state") or "").strip() != STATUS_COLLECTION_OK:
        return False

    scheduler_status = str(status.get("scheduler_status") or "").strip().upper()
    if scheduler_status != "COMPLETED":
        return False

    job_states = dict(status.get("job_states") or {})
    total_jobs = int(status.get("job_count") or sum(int(value) for value in job_states.values()))
    finished_jobs = int(job_states.get("finished", 0))
    if total_jobs <= 0 or finished_jobs != total_jobs:
        return False

    if int(status.get("failed_job_count", 0)) != 0:
        return False

    return all(
        int(count) == 0 for state, count in job_states.items() if str(state) != "finished"
    )


def is_cached_killed(status: dict[str, Any]) -> bool:
    if not is_killed_server_status(status.get("server_status")):
        return False
    return str(status.get("status_collection_state") or "").strip() in {
        STATUS_COLLECTION_OK,
        STATUS_COLLECTION_HEADER_ONLY_KILLED,
    }


def should_skip_live_refresh(
    status: dict[str, Any], *, force_terminal_refresh: bool
) -> bool:
    if force_terminal_refresh:
        return False
    return is_cached_completed_and_all_finished(status) or is_cached_killed(status)


def hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def empty_state(manifest_path: Path, task_root: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": now_iso(),
        "manifest": str(manifest_path),
        "cwd": str(task_root),
        "status_args": [],
        "recovery_suffix": RECOVERY_SUFFIX,
        "families": {},
        "attempts": {},
        "query_failures": [],
        "header_only_killed_tasks": [],
        "task_count": 0,
    }


def ensure_state_shape(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("schema_version", SCHEMA_VERSION)
    state.setdefault("updated_at", now_iso())
    state.setdefault("manifest", "")
    state.setdefault("cwd", "")
    state.setdefault("status_args", [])
    state.setdefault("recovery_suffix", RECOVERY_SUFFIX)
    state.setdefault("families", {})
    state.setdefault("attempts", {})
    state.setdefault("query_failures", [])
    state.setdefault("header_only_killed_tasks", [])
    state.setdefault("task_count", 0)
    for attempt in state["attempts"].values():
        attempt.setdefault("family_id", attempt.get("task_dir"))
        attempt.setdefault("parent_attempt_id", None)
        attempt.setdefault("generation", 0)
        attempt.setdefault("planned_lumi_mask", None)
        attempt.setdefault("planned_lumi_source", None)
        attempt.setdefault("status_revision", None)
        attempt.setdefault("status", {"status_collection_state": STATUS_COLLECTION_NOT_COLLECTED})
        attempt["status"].setdefault("hold_since", None)
        attempt.setdefault("recovery", {})
    return state


def infer_request_lineage(request_name: str, recovery_suffix: str) -> tuple[str, int]:
    import re

    numbered_pattern = re.compile(
        rf"^(?P<root>.+)__{re.escape(recovery_suffix)}(?P<generation>\d+)$"
    )
    match = numbered_pattern.match(request_name)
    if match:
        return match.group("root"), int(match.group("generation"))
    return request_name, 0


def rebuild_families(state: dict[str, Any]) -> None:
    rebuild_chain_index(state)


def make_status_payload(
    summary: dict[str, Any],
    jobs: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    return {
        "collected_at": now_iso(),
        "task_name": summary.get("task_name"),
        "server_status": summary.get("server_status"),
        "scheduler_status": summary.get("scheduler_status"),
        "dashboard_url": summary.get("dashboard_url"),
        "status_collection_state": summary.get("status_collection_state"),
        "query_error": summary.get("query_error"),
        "query_warning": summary.get("query_warning"),
        "hold_since": None,
        "job_count": int(summary.get("job_count", 0)),
        "job_states": dict(summary.get("job_states", {})),
        "failed_job_count": int(summary.get("failed_job_count", 0)),
        "failed_job_ids": [str(job_id) for job_id in summary.get("failed_job_ids", [])],
        "jobs": jobs,
    }


def clear_stale_recovery(recovery: dict[str, Any]) -> dict[str, Any]:
    preserved = {
        "submitted_child_attempt_id": recovery.get("submitted_child_attempt_id"),
        "submitted_at": recovery.get("submitted_at"),
    }
    return {
        **preserved,
        "classification": recovery.get("classification", "no_action"),
        "recovery_job_ids": [],
        "repeated_failure_job_ids": [],
        "failed_retry_threshold": recovery.get("failed_retry_threshold"),
        "recovery_state_counts": {},
        "blocking_job_ids": [],
        "blocking_state_counts": {},
        "skipped_jobs_without_time": [],
        "kill_required": False,
        "derived_from_revision": None,
        "resolved_lumi_action": None,
        "resolved_lumi_source": None,
        "resolved_lumi_mask": None,
    }


def merge_attempt_status(
    existing_attempt: dict[str, Any] | None,
    cfg: str,
    task_dir: Path,
    status: dict[str, Any],
) -> dict[str, Any]:
    existing_attempt = dict(existing_attempt or {})
    request_name = str(existing_attempt.get("request_name") or Path(cfg).stem)
    root_request_name, generation = infer_request_lineage(request_name, RECOVERY_SUFFIX)
    task_dir_name = task_dir.name
    family_id = str(existing_attempt.get("family_id") or (task_dir_name if generation == 0 else task_dir_name))
    status_revision = hash_payload(
        {key: value for key, value in status.items() if key != "collected_at"}
    )
    recovery = dict(existing_attempt.get("recovery", {}))
    if recovery.get("derived_from_revision") != status_revision:
        recovery = clear_stale_recovery(recovery)
    existing_status = dict(existing_attempt.get("status", {}))
    if is_holding_resubmit_server_status(status.get("server_status")):
        if is_holding_resubmit_server_status(existing_status.get("server_status")):
            status["hold_since"] = (
                existing_status.get("hold_since")
                or existing_status.get("collected_at")
                or status.get("collected_at")
            )
        else:
            status["hold_since"] = status.get("collected_at")
    else:
        status["hold_since"] = None

    return {
        **existing_attempt,
        "task_dir": task_dir_name,
        "cfg": cfg,
        "cfg_path": str(Path(cfg).resolve() if Path(cfg).exists() else Path(cfg)),
        "task_path": str(task_dir.resolve()),
        "request_name": request_name,
        "family_id": family_id,
        "parent_attempt_id": existing_attempt.get("parent_attempt_id"),
        "generation": int(existing_attempt.get("generation", generation)),
        "planned_lumi_mask": existing_attempt.get("planned_lumi_mask"),
        "planned_lumi_source": existing_attempt.get("planned_lumi_source"),
        "status_revision": status_revision,
        "status": status,
        "recovery": recovery,
    }


def load_existing_state(state_path: Path, manifest_path: Path, task_root: Path) -> dict[str, Any]:
    if state_path.exists():
        return ensure_state_shape(load_json(state_path))
    return empty_state(manifest_path, task_root)


def ensure_family_index_exists(state: dict[str, Any]) -> None:
    if state.get("attempts") and not state.get("families"):
        rebuild_families(state)


def latest_attempt_ids(state: dict[str, Any]) -> list[str]:
    if not state.get("attempts"):
        return []

    ensure_family_index_exists(state)
    families = state.get("families", {})
    if not families:
        return sorted(state["attempts"])

    latest_ids: list[str] = []
    seen: set[str] = set()
    for family_id in sorted(families):
        family = families[family_id]
        root_task_dir = str(family.get("root_task_dir") or family_id)
        latest_id = str(family.get("latest_attempt_id") or get_latest_task(state, root_task_dir))
        if latest_id in state["attempts"] and latest_id not in seen:
            latest_ids.append(latest_id)
            seen.add(latest_id)
    return latest_ids


def latest_query_failures(state: dict[str, Any]) -> list[str]:
    latest_ids = set(latest_attempt_ids(state))
    return sorted(task_dir for task_dir in state.get("query_failures", []) if task_dir in latest_ids)


def make_cached_task_summary(attempt: dict[str, Any], summary_note: str) -> dict[str, Any]:
    status = dict(attempt.get("status", {}))
    task_path = str(attempt.get("task_path") or attempt.get("task_dir") or "")
    return {
        "cfg": str(attempt.get("cfg_path") or attempt.get("cfg") or ""),
        "task_dir": str(attempt.get("task_dir") or Path(task_path).name),
        "task_path": task_path,
        "task_name": status.get("task_name"),
        "server_status": status.get("server_status"),
        "scheduler_status": status.get("scheduler_status"),
        "dashboard_url": status.get("dashboard_url"),
        "job_count": int(status.get("job_count", 0)),
        "job_states": dict(status.get("job_states", {})),
        "failed_job_count": int(status.get("failed_job_count", 0)),
        "failed_job_ids": [str(job_id) for job_id in status.get("failed_job_ids", [])],
        "status_collection_state": status.get(
            "status_collection_state", STATUS_COLLECTION_NOT_COLLECTED
        ),
        "query_error": status.get("query_error"),
        "query_warning": status.get("query_warning"),
        "summary_note": summary_note,
    }


def current_query_metadata(state: dict[str, Any]) -> tuple[list[str], list[str]]:
    query_failures: list[str] = []
    header_only_killed_tasks: list[str] = []
    for attempt_id, attempt in state.get("attempts", {}).items():
        status = dict(attempt.get("status", {}))
        status_state = str(status.get("status_collection_state") or "")
        if status_state == STATUS_COLLECTION_FATAL_ERROR:
            query_failures.append(str(attempt_id))
        if status_state == STATUS_COLLECTION_HEADER_ONLY_KILLED:
            header_only_killed_tasks.append(str(attempt_id))
    return sorted(query_failures), sorted(header_only_killed_tasks)


def query_entries(
    manifest_entries: list[str], task_root: Path, state: dict[str, Any]
) -> list[tuple[str, Path]]:
    entries: dict[str, tuple[str, Path]] = {}
    for cfg in manifest_entries:
        task_dir = task_dir_from_cfg(task_root, cfg)
        entries[task_dir.name] = (cfg, task_dir)
    for attempt in state.get("attempts", {}).values():
        cfg = str(attempt.get("cfg_path") or attempt.get("cfg") or "")
        task_path = Path(str(attempt.get("task_path") or (task_root / attempt["task_dir"])))
        if not cfg:
            continue
        entries.setdefault(task_path.name, (cfg, task_path))
    return list(entries.values())


def query_latest_entries(
    manifest_entries: list[str], task_root: Path, state: dict[str, Any]
) -> list[tuple[str, Path]]:
    entries: dict[str, tuple[str, Path]] = {}
    for task_dir_name in latest_attempt_ids(state):
        attempt = state["attempts"][task_dir_name]
        cfg = str(attempt.get("cfg_path") or attempt.get("cfg") or "")
        if not cfg:
            continue
        task_path = Path(str(attempt.get("task_path") or (task_root / task_dir_name)))
        entries[task_path.name] = (cfg, task_path)

    for cfg in manifest_entries:
        task_dir = task_dir_from_cfg(task_root, cfg)
        if task_dir.name not in state.get("attempts", {}):
            entries[task_dir.name] = (cfg, task_dir)

    return [entries[name] for name in sorted(entries)]


def run_raw_queries(entries: list[tuple[str, Path]], extra_args: list[str]) -> int:
    exit_code = 0
    for _cfg, task_dir in entries:
        completed, _cmd = query_task_status_raw(task_dir, extra_args)
        if completed.stdout:
            sys.stdout.write(completed.stdout)
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            exit_code = 1
    return exit_code


def record_query_metadata(
    state: dict[str, Any],
) -> None:
    query_failures, header_only_killed_tasks = current_query_metadata(state)
    state["query_failures"] = sorted(query_failures)
    state["header_only_killed_tasks"] = sorted(header_only_killed_tasks)
    state["task_count"] = len(state["attempts"])
    state["updated_at"] = now_iso()


def run_collect(args: argparse.Namespace, extra_args: list[str]) -> int:
    ensure_compatible_status_args(extra_args)

    manifest_path = Path(args.manifest).resolve()
    state_path = resolve_state_file(args).resolve()
    task_root = Path.cwd().resolve()
    state = load_existing_state(state_path, manifest_path, task_root)
    state["manifest"] = str(manifest_path)
    state["cwd"] = str(task_root)
    state["status_args"] = list(extra_args)

    query_failures: list[str] = []
    family_structure_changed = bool(state.get("attempts")) and not state.get("families")

    for cfg, task_dir in query_entries(read_manifest(manifest_path), task_root, state):
        task_dir_name = task_dir.name
        existing_attempt = state["attempts"].get(task_dir_name)
        existing_status = dict((existing_attempt or {}).get("status", {}))
        if existing_attempt and should_skip_live_refresh(
            existing_status,
            force_terminal_refresh=bool(args.refresh_terminal_statuses),
        ):
            print(
                format_task_summary(
                    make_cached_task_summary(
                        existing_attempt, "note=cached-terminal-skip"
                    )
                )
            )
            continue

        summary, payload, _stdout, _stderr, _cmd = build_task_summary(cfg, task_dir, extra_args)
        status = make_status_payload(summary, payload)
        if task_dir_name not in state["attempts"]:
            family_structure_changed = True
        state["attempts"][task_dir_name] = merge_attempt_status(
            state["attempts"].get(task_dir_name),
            cfg,
            task_dir,
            status,
        )

        if status["status_collection_state"] == STATUS_COLLECTION_FATAL_ERROR:
            query_failures.append(task_dir_name)
        print(format_task_summary(summary))

    if family_structure_changed:
        rebuild_families(state)
    record_query_metadata(state)
    write_json(state_path, state)
    return 1 if query_failures else 0


def run_query_all(args: argparse.Namespace, extra_args: list[str]) -> int:
    if not args.no_update_cache:
        if args.raw_output:
            raise ValueError("--raw-output requires --no-update-cache.")
        return run_collect(args, extra_args)

    manifest_path = Path(args.manifest).resolve()
    state_path = resolve_state_file(args).resolve()
    task_root = Path.cwd().resolve()
    state = load_existing_state(state_path, manifest_path, task_root)
    entries = query_entries(read_manifest(manifest_path), task_root, state)

    if args.raw_output:
        return run_raw_queries(entries, extra_args)

    ensure_compatible_status_args(extra_args)
    query_failures: list[str] = []
    for cfg, task_dir in entries:
        summary, _payload, _stdout, _stderr, _cmd = build_task_summary(cfg, task_dir, extra_args)
        if summary["status_collection_state"] == STATUS_COLLECTION_FATAL_ERROR:
            query_failures.append(task_dir.name)
        print(format_task_summary(summary))
    return 1 if query_failures else 0


def run_query_latest(args: argparse.Namespace, extra_args: list[str]) -> int:
    if args.raw_output and not args.no_update_cache:
        raise ValueError("--raw-output requires --no-update-cache.")

    manifest_path = Path(args.manifest).resolve()
    state_path = resolve_state_file(args).resolve()
    task_root = Path.cwd().resolve()
    state = load_existing_state(state_path, manifest_path, task_root)
    ensure_family_index_exists(state)
    entries = query_latest_entries(read_manifest(manifest_path), task_root, state)

    if args.no_update_cache and args.raw_output:
        return run_raw_queries(entries, extra_args)

    ensure_compatible_status_args(extra_args)
    query_failures: list[str] = []
    family_structure_changed = False

    for cfg, task_dir in entries:
        task_dir_name = task_dir.name
        existing_attempt = state["attempts"].get(task_dir_name)
        existing_status = dict((existing_attempt or {}).get("status", {}))
        if (not args.no_update_cache) and existing_attempt and should_skip_live_refresh(
            existing_status,
            force_terminal_refresh=bool(args.refresh_terminal_statuses),
        ):
            print(
                format_task_summary(
                    make_cached_task_summary(
                        existing_attempt, "note=cached-terminal-skip"
                    )
                )
            )
            continue

        summary, payload, _stdout, _stderr, _cmd = build_task_summary(cfg, task_dir, extra_args)
        if summary["status_collection_state"] == STATUS_COLLECTION_FATAL_ERROR:
            query_failures.append(task_dir_name)
        print(format_task_summary(summary))

        if args.no_update_cache:
            continue

        if task_dir_name not in state["attempts"]:
            family_structure_changed = True
        status = make_status_payload(summary, payload)
        state["attempts"][task_dir_name] = merge_attempt_status(
            state["attempts"].get(task_dir_name),
            cfg,
            task_dir,
            status,
        )

    if args.no_update_cache:
        return 1 if query_failures else 0

    state["manifest"] = str(manifest_path)
    state["cwd"] = str(task_root)
    state["status_args"] = list(extra_args)
    if family_structure_changed:
        rebuild_families(state)
    record_query_metadata(state)
    write_json(state_path, state)
    return 1 if query_failures else 0


def format_job_states(job_states: dict[str, int]) -> str:
    if not job_states:
        return "none"
    return " ".join(f"{state}={count}" for state, count in sorted(job_states.items()))


def format_cache_display(state: dict[str, Any], state_path: Path) -> str:
    ensure_family_index_exists(state)
    lines = [
        f"Cache file: {state_path}",
        f"Updated at: {state.get('updated_at', 'unknown')}",
        f"Manifest: {state.get('manifest', '')}",
        f"Families: {len(state.get('families', {}))}",
        f"Attempts: {len(state.get('attempts', {}))}",
        "Query failures: "
        + (", ".join(latest_query_failures(state)) or "none"),
        "Header-only killed: "
        + (", ".join(state.get("header_only_killed_tasks", [])) or "none"),
    ]

    families = state.get("families", {})
    if not families:
        return "\n".join(lines)

    for family_id in sorted(families):
        family = families[family_id]
        attempt_order = list(family.get("attempt_order", []))
        latest_id = str(family.get("latest_attempt_id") or "")
        lines.extend(
            [
                "",
                f"Family {family_id}",
                f"  root={family.get('root_task_dir', '')}",
                f"  latest={latest_id}",
                f"  chain={' -> '.join(attempt_order) if attempt_order else '(empty)'}",
            ]
        )
        for attempt_id in attempt_order:
            attempt = state["attempts"].get(attempt_id, {})
            status = attempt.get("status", {})
            marker = " latest" if attempt_id == latest_id else ""
            warning = status.get("query_warning")
            error = status.get("query_error")
            message = f" warning={warning}" if warning else ""
            if error:
                message = f" error={error}"
            lines.append(
                "  - "
                f"{attempt_id}{marker} "
                f"server={status.get('server_status') or 'unknown'} "
                f"scheduler={status.get('scheduler_status') or 'unknown'} "
                f"collection={status.get('status_collection_state') or STATUS_COLLECTION_NOT_COLLECTED} "
                f"failed={status.get('failed_job_count', 0)} "
                f"states={format_job_states(status.get('job_states', {}))}"
                f"{message}"
            )
    return "\n".join(lines)


def run_display_cache(args: argparse.Namespace) -> int:
    state_path = resolve_state_file(args).resolve()
    if not state_path.exists():
        raise FileNotFoundError(
            f"Missing state file {state_path}. Run ./status.sh first."
        )

    state = ensure_state_shape(load_json(state_path))
    print(format_cache_display(state, state_path))
    return 0


def iter_latest_failed_entries(
    state: dict[str, Any],
) -> list[tuple[str, list[str], int]]:
    entries: list[tuple[str, list[str], int]] = []
    for task_dir_name in latest_attempt_ids(state):
        attempt = state["attempts"][task_dir_name]
        status = attempt.get("status", {})
        if not is_resubmit_eligible_status(status):
            continue
        failed_job_ids = [str(job_id) for job_id in status.get("failed_job_ids", [])]
        if not failed_job_ids:
            continue
        entries.append(
            (
                str(attempt["task_dir"]),
                failed_job_ids,
                int(status.get("failed_job_count", len(failed_job_ids))),
            )
        )
    return entries


def run_list_failed(args: argparse.Namespace) -> int:
    state_path = resolve_state_file(args).resolve()
    if not state_path.exists():
        raise FileNotFoundError(
            f"Missing state file {state_path}. Run ./status.sh first."
        )

    state = ensure_state_shape(load_json(state_path))
    query_failures = latest_query_failures(state)
    if query_failures:
        print(
            "Status snapshot contains query failures; refresh status before resubmitting: "
            + ", ".join(query_failures),
            file=sys.stderr,
        )
        return 1

    for task_dir, failed_job_ids, failed_count in iter_latest_failed_entries(state):
        print(
            "\t".join(
                [
                    task_dir,
                    ",".join(failed_job_ids),
                    str(failed_count),
                ]
            )
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args, extra_args = parse_args(argv)
    if args.command == "collect":
        ensure_cmssw_env()
        ensure_proxy_env()
        return run_collect(args, extra_args)
    if args.command == "query-all":
        ensure_cmssw_env()
        ensure_proxy_env()
        return run_query_all(args, extra_args)
    if args.command == "query-latest":
        ensure_cmssw_env()
        ensure_proxy_env()
        return run_query_latest(args, extra_args)
    if extra_args:
        raise ValueError(
            f"Unexpected extra arguments for {args.command}: {' '.join(extra_args)}"
        )
    if args.command == "display-cache":
        return run_display_cache(args)
    return run_list_failed(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI error reporting
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
