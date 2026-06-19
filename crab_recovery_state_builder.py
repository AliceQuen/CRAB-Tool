#!/usr/bin/env python3
"""Maintain recovery metadata inside one authoritative CRAB state file."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from FWCore.PythonUtilities.LumiList import LumiList
from pathlib import Path
from typing import Any

from crab_config_literals import (
    ParsedCrabConfig,
    emit_wmcore_crab_config,
    load_cfg_metadata_via_literals,
    merge_literal_assignments,
    parse_literal_crab_config,
    parse_literal_crab_config_file,
    render_template,
)
from crab_recovery_chain import (
    ChainAppendSpec,
    append_after,
    get_latest_task,
    rebuild_chain_index,
)

TIME_THRESHOLD_STATES = {"idle", "cooloff"}
NON_FINISHED_STATES = {
    "idle",
    "cooloff",
    "unsubmitted",
    "running",
    "transferring",
    "failed",
}
DEFAULT_STUCK_HOURS = 48.0
RECOVERY_SUFFIX = "recover"
STATE_NAME = "latest_state.json"
PLAN_NAME = STATE_NAME
CONFIG_MANIFEST_NAME = "generated_recovery_configs.txt"
LINEAGE_NAME = "task_lineage.json"
TRACKED_CONFIGS_NAME = "tracked_configs.txt"
STATUS_COLLECTION_OK = "ok_json"
STATUS_COLLECTION_HEADER_ONLY_KILLED = "header_only_killed"
STATUS_COLLECTION_FATAL_ERROR = "fatal_error"
STATUS_COLLECTION_NOT_COLLECTED = "not_collected"
RECOVERY_RENDER_CLASSES = {
    "recovery_candidate",
    "mixed",
    "killed_recovery_candidate",
    "holding_resubmit_recovery_candidate",
}
DEFAULT_RECOVERY_UNITS_PER_JOB = 100
DEFAULT_RECOVERY_NUM_CORES = 1
DEFAULT_RECOVERY_MAX_MEMORY_MB = 2000
DEFAULT_RECOVERY_PYCFG_PARAM_OVERRIDES = {
    "numThreads": 1,
    "numStreams": 0,
}


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


def normalize_local_lumi_path(
    raw_value: str, *, base_dir: Path | None = None
) -> Path:
    if raw_value.startswith(("http://", "https://")):
        raise ValueError(
            "URL-based lumi masks are not supported by recovery-chain validation."
        )
    path = Path(raw_value)
    if not path.is_absolute() and base_dir is not None:
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()
    return path


def _is_compact_list_dict(value: dict[Any, Any]) -> bool:
    return all(
        isinstance(ranges, list)
        and all(
            isinstance(pair, (list, tuple))
            and len(pair) == 2
            and all(isinstance(item, int) for item in pair)
            for pair in ranges
        )
        for ranges in value.values()
    )


def _is_runs_and_lumis_dict(value: dict[Any, Any]) -> bool:
    return all(
        isinstance(lumis, list) and all(isinstance(item, int) for item in lumis)
        for lumis in value.values()
    )


def _is_run_lumi_pair_list(value: list[Any]) -> bool:
    return all(
        isinstance(item, (list, tuple))
        and len(item) == 2
        and all(isinstance(part, int) for part in item)
        for item in value
    )


def load_lumi_json_payload(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def lumi_list_from_value(value: Any, *, base_dir: Path | None = None) -> LumiList:
    if isinstance(value, LumiList):
        return value
    if isinstance(value, str):
        payload = load_lumi_json_payload(
            normalize_local_lumi_path(value, base_dir=base_dir)
        )
        return lumi_list_from_value(payload)
    if isinstance(value, dict):
        if _is_compact_list_dict(value):
            return LumiList(compactList=value)
        if _is_runs_and_lumis_dict(value):
            return LumiList(runsAndLumis=value)
        raise ValueError(f"Unsupported lumi-mask dict shape: {value!r}")
    if isinstance(value, list):
        if not _is_run_lumi_pair_list(value):
            raise ValueError("List lumi masks must be a list of [run, lumi] pairs.")
        return LumiList(lumis=value)
    raise ValueError(f"Unsupported lumi mask value: {value!r}")


def compact_lumi_dict(
    value: Any, *, base_dir: Path | None = None
) -> dict[str, list[list[int]]]:
    lumi_list = lumi_list_from_value(value, base_dir=base_dir)
    compact = lumi_list.getCompactList()
    return {
        str(run): [[int(pair[0]), int(pair[1])] for pair in ranges]
        for run, ranges in sorted(compact.items(), key=lambda item: int(item[0]))
    }


def normalize_state_lumi_mask(
    value: Any, *, base_dir: Path | None = None
) -> dict[str, list[list[int]]] | None:
    if value is None:
        return None
    return compact_lumi_dict(value, base_dir=base_dir)


def exact_same_lumis(
    left: Any,
    right: Any,
    *,
    left_base: Path | None = None,
    right_base: Path | None = None,
) -> bool:
    left_ll = LumiList(compactList=compact_lumi_dict(left, base_dir=left_base))
    right_ll = LumiList(compactList=compact_lumi_dict(right, base_dir=right_base))
    return not (left_ll - right_ll).getCompactList() and not (
        right_ll - left_ll
    ).getCompactList()


def add_state_file_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state-file",
        default=f"status_cache/{STATE_NAME}",
        help="Authoritative unified CRAB state file.",
    )
    parser.add_argument(
        "--plan-file",
        default=None,
        help="Deprecated alias for --state-file.",
    )
    parser.add_argument(
        "--summary-file",
        default=None,
        help="Deprecated legacy status-summary path. Used only for one-time migration.",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh recovery metadata, resolve lumi masks, render configs, and record "
            "linear recovery chains inside one authoritative state file."
        ),
        formatter_class=HelpFormatter,
        epilog=(
            "Examples:\n"
            "  crab_recovery_task_builder.py refresh-recovery --state-file status_cache/latest_state.json\n"
            "  crab_recovery_task_builder.py list-executable --state-file status_cache/latest_state.json\n"
            "  crab_recovery_task_builder.py record-submission --state-file status_cache/latest_state.json --task crab_task\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh_parser = subparsers.add_parser(
        "refresh-recovery",
        help="Refresh derived recovery metadata from the authoritative state file.",
        formatter_class=HelpFormatter,
        epilog=(
            "Output files:\n"
            "  <state-file> (updated in place)\n"
            "  <output-dir>/generated_recovery_configs.txt (after render-all)\n"
            "  <output-dir>/reports/<task>/notFinishedLumis.json (preserved by the shell wrapper)\n\n"
            "Updates the recovery section of latest_state.json in place so every\n"
            "attempt in a family chain stays synchronized with the same status revision."
        ),
    )
    add_state_file_argument(refresh_parser)
    refresh_parser.add_argument(
        "--output-dir",
        default="recovery_cache",
        help="Directory where preserved report artifacts and rendered configs live.",
    )
    refresh_parser.add_argument(
        "--stuck-hours",
        type=float,
        default=DEFAULT_STUCK_HOURS,
        help="Minimum idle/cooloff age required to classify a job for recovery.",
    )
    refresh_parser.add_argument(
        "--recovery-suffix",
        default=RECOVERY_SUFFIX,
        help="Suffix family used for generated recovery request names.",
    )

    plan_parser = subparsers.add_parser(
        "plan",
        help="Deprecated alias for refresh-recovery.",
        formatter_class=HelpFormatter,
        epilog=(
            "Output files:\n"
            "  <state-file> (updated in place)\n\n"
            "This compatibility alias keeps the old command shape, but the only\n"
            "authoritative cache is latest_state.json."
        ),
    )
    add_state_file_argument(plan_parser)
    plan_parser.add_argument("--output-dir", default="recovery_cache")
    plan_parser.add_argument("--stuck-hours", type=float, default=DEFAULT_STUCK_HOURS)
    plan_parser.add_argument("--recovery-suffix", default=RECOVERY_SUFFIX)

    render_parser = subparsers.add_parser(
        "render-one",
        help="Render one recovery CRAB config from the unified state file.",
        formatter_class=HelpFormatter,
    )
    add_state_file_argument(render_parser)
    render_parser.add_argument("--task", required=True)

    render_all_parser = subparsers.add_parser(
        "render-all",
        help="Render recovery configs for every executable task in the unified state file.",
        formatter_class=HelpFormatter,
    )
    add_state_file_argument(render_all_parser)

    list_parser = subparsers.add_parser(
        "list-executable",
        help="List recovery tasks that should be executed, optionally including mixed tasks.",
        formatter_class=HelpFormatter,
        epilog=(
            "Output columns:\n"
            "  task_dir<TAB>task_path<TAB>report_dir<TAB>preserved_not_finished_lumis"
            "<TAB>recover_cfg<TAB>classification"
        ),
    )
    add_state_file_argument(list_parser)
    list_parser.add_argument("--include-mixed", action="store_true")

    resolve_parser = subparsers.add_parser(
        "resolve-lumi-mask",
        help="Resolve the recovery lumi mask for one attempt in the unified state file.",
        formatter_class=HelpFormatter,
        epilog="Output columns:\n  action<TAB>source<TAB>path",
    )
    add_state_file_argument(resolve_parser)
    resolve_parser.add_argument("--task", required=True)
    resolve_parser.add_argument(
        "--runtime-server-status",
        default=None,
        help="Optional live CRAB server status that can refine killed-task fallback handling.",
    )

    record_parser = subparsers.add_parser(
        "record-submission",
        help="Record a successfully submitted recovery child in the linear family chain.",
        formatter_class=HelpFormatter,
    )
    add_state_file_argument(record_parser)
    record_parser.add_argument("--task", required=True)

    add_parser = subparsers.add_parser(
        "add-to-chain",
        help="Register an already-existing recovery child after exact lumi-coverage validation.",
        formatter_class=HelpFormatter,
    )
    add_state_file_argument(add_parser)
    add_parser.add_argument("--parent-task", required=True)
    add_parser.add_argument("--child-task-dir", required=True)
    add_parser.add_argument("--child-cfg", required=True)
    add_parser.add_argument(
        "--child-task-path",
        default=None,
        help="Explicit task path for the child. Defaults to <state cwd>/<child-task-dir>.",
    )

    return parser.parse_args(argv)


def resolve_state_file_arg(args: argparse.Namespace) -> Path:
    if getattr(args, "plan_file", None):
        return Path(args.plan_file)
    if getattr(args, "summary_file", None):
        legacy_path = Path(args.summary_file)
        if legacy_path.name == "latest_summary.json":
            return legacy_path.with_name(STATE_NAME)
        return legacy_path
    return Path(args.state_file)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}.")
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp_path, path)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_snapshot_time(raw: str | None) -> datetime:
    if raw:
        return datetime.fromisoformat(raw)
    return datetime.now(timezone.utc)


def is_killed_server_status(server_status: str | None) -> bool:
    return (server_status or "").strip().upper() == "KILLED"


def is_holding_resubmit_server_status(server_status: str | None) -> bool:
    return (server_status or "").strip().upper().startswith(
        "HOLDING ON COMMAND RESUBMIT"
    )


def hold_age_hours(status: dict[str, Any], snapshot_time: datetime) -> float | None:
    raw_hold_since = status.get("hold_since")
    if not raw_hold_since:
        return None
    try:
        hold_since = datetime.fromisoformat(str(raw_hold_since))
    except ValueError:
        return None
    return (snapshot_time - hold_since).total_seconds() / 3600.0


def resolve_cfg_path(crab_data_dir: Path, cfg: str) -> Path:
    cfg_path = Path(cfg)
    if cfg_path.is_absolute():
        return cfg_path.resolve()
    return (crab_data_dir / cfg_path).resolve()


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "updated_at": now_iso(),
        "manifest": "",
        "cwd": "",
        "status_args": [],
        "stuck_hours": DEFAULT_STUCK_HOURS,
        "recovery_suffix": RECOVERY_SUFFIX,
        "families": {},
        "attempts": {},
        "query_failures": [],
        "header_only_killed_tasks": [],
        "task_count": 0,
    }


def ensure_state_shape(state: dict[str, Any]) -> dict[str, Any]:
    merged = empty_state()
    merged.update(state)
    merged["families"] = dict(merged.get("families", {}))
    merged["attempts"] = dict(merged.get("attempts", {}))
    lumi_base_dir = Path(str(merged.get("cwd") or Path.cwd())).resolve()
    for attempt_id, attempt in merged["attempts"].items():
        attempt.setdefault("task_dir", attempt_id)
        attempt.setdefault("cfg", attempt.get("cfg_path"))
        attempt.setdefault("cfg_path", attempt.get("cfg"))
        attempt.setdefault("task_path", "")
        attempt.setdefault(
            "request_name", Path(str(attempt.get("cfg_path") or attempt_id)).stem
        )
        attempt.setdefault("family_id", attempt_id)
        attempt.setdefault("parent_attempt_id", None)
        attempt.setdefault("generation", 0)
        attempt.setdefault("planned_lumi_mask", None)
        attempt.setdefault("planned_lumi_source", None)
        attempt.setdefault("original_lumi_mask", None)
        attempt.setdefault("original_units_per_job", None)
        attempt.setdefault("publication_enabled", False)
        attempt.setdefault("original_output_dataset_tag", None)
        attempt.setdefault("config_metadata", None)
        attempt.setdefault("status_revision", None)
        attempt.setdefault(
            "status", {"status_collection_state": STATUS_COLLECTION_NOT_COLLECTED}
        )
        attempt.setdefault("recovery", {})
        attempt.setdefault("artifacts", {})
        if attempt.get("planned_lumi_mask") is not None:
            attempt["planned_lumi_mask"] = normalize_state_lumi_mask(
                attempt.get("planned_lumi_mask"), base_dir=lumi_base_dir
            )
        if attempt.get("original_lumi_mask") is not None:
            attempt["original_lumi_mask"] = normalize_state_lumi_mask(
                attempt.get("original_lumi_mask"), base_dir=lumi_base_dir
            )
        recovery = attempt.get("recovery", {})
        if recovery.get("resolved_lumi_mask") is not None:
            recovery["resolved_lumi_mask"] = normalize_state_lumi_mask(
                recovery.get("resolved_lumi_mask"), base_dir=lumi_base_dir
            )
        config_metadata = attempt.get("config_metadata")
        if isinstance(config_metadata, dict):
            attempt["config_metadata"] = normalize_attempt_config_metadata(
                config_metadata
            )
    rebuild_families(merged)
    return merged


def infer_request_lineage(request_name: str, recovery_suffix: str) -> tuple[str, int]:
    numbered_pattern = re.compile(
        rf"^(?P<root>.+)__{re.escape(recovery_suffix)}(?P<generation>\d+)$"
    )
    match = numbered_pattern.match(request_name)
    if match:
        return match.group("root"), int(match.group("generation"))

    legacy_pattern = re.compile(
        rf"^(?P<root>.+?)(?P<suffixes>(?:_{re.escape(recovery_suffix)})+)$"
    )
    match = legacy_pattern.match(request_name)
    if match:
        suffixes = match.group("suffixes")
        generation = suffixes.count(f"_{recovery_suffix}")
        return match.group("root"), generation

    return request_name, 0


def build_recovery_request_name(
    root_request_name: str, generation: int, recovery_suffix: str
) -> str:
    if generation <= 0:
        return root_request_name
    return f"{root_request_name}__{recovery_suffix}{generation}"


def rebuild_families(state: dict[str, Any]) -> None:
    rebuild_chain_index(state)


def state_needs_legacy_migration(state_path: Path) -> bool:
    return not state_path.exists() and state_path.with_name("latest_summary.json").exists()


def migrate_legacy_state(
    state_path: Path, recovery_output_dir: Path | None = None
) -> dict[str, Any]:
    summary_path = state_path.with_name("latest_summary.json")
    summary = load_json(summary_path)
    state = empty_state()
    state["manifest"] = str(summary.get("manifest") or "")
    state["cwd"] = str(summary.get("cwd") or Path.cwd())
    state["updated_at"] = str(summary.get("generated_at") or now_iso())
    for task in summary.get("tasks", []):
        jobs = None
        task_status_file = str(task.get("task_status_file") or "")
        if task_status_file:
            payload_path = summary_path.parent / task_status_file
            if payload_path.exists():
                payload = load_json(payload_path)
                jobs = payload.get("jobs")
        request_name = Path(str(task["cfg"])).stem
        status = {
            "collected_at": str(summary.get("generated_at") or now_iso()),
            "task_name": task.get("task_name"),
            "server_status": task.get("server_status"),
            "scheduler_status": task.get("scheduler_status"),
            "dashboard_url": task.get("dashboard_url"),
            "status_collection_state": infer_status_collection_state(task),
            "query_error": task.get("query_error"),
            "query_warning": task.get("query_warning"),
            "job_count": int(task.get("job_count", 0)),
            "job_states": dict(task.get("job_states", {})),
            "failed_job_count": int(task.get("failed_job_count", 0)),
            "failed_job_ids": [str(job_id) for job_id in task.get("failed_job_ids", [])],
            "jobs": jobs,
        }
        task_dir = str(task["task_dir"])
        state["attempts"][task_dir] = {
            "task_dir": task_dir,
            "cfg": str(task["cfg"]),
            "cfg_path": str(
                resolve_cfg_path(
                    Path(str(summary.get("cwd") or Path.cwd())), str(task["cfg"])
                )
            ),
            "task_path": str(task["task_path"]),
            "request_name": request_name,
            "family_id": task_dir,
            "parent_attempt_id": None,
            "generation": 0,
            "planned_lumi_mask": None,
            "planned_lumi_source": None,
            "status_revision": None,
            "status": status,
            "recovery": {},
            "artifacts": {},
        }

    if recovery_output_dir is not None:
        lineage_path = recovery_output_dir / "task_lineage.json"
        if lineage_path.exists():
            lineage = load_json(lineage_path)
            for task_dir, node in lineage.get("nodes", {}).items():
                if task_dir in state["attempts"]:
                    continue
                cfg_path = str(node.get("cfg_path") or node.get("cfg") or "")
                request_name = str(
                    node.get("request_name") or Path(cfg_path or task_dir).stem
                )
                generation = int(node.get("generation", 0))
                state["attempts"][task_dir] = {
                    "task_dir": task_dir,
                    "cfg": cfg_path,
                    "cfg_path": cfg_path,
                    "task_path": str(node.get("task_path") or ""),
                    "request_name": request_name,
                    "family_id": str(node.get("parent_task_dir") or task_dir),
                    "parent_attempt_id": node.get("parent_task_dir"),
                    "generation": generation,
                    "planned_lumi_mask": node.get("planned_lumi_mask")
                    or node.get("original_lumi_mask"),
                    "planned_lumi_source": node.get("planned_lumi_source")
                    or (
                        "legacy_lineage"
                        if node.get("planned_lumi_mask")
                        or node.get("original_lumi_mask")
                        else None
                    ),
                    "status_revision": None,
                    "status": {
                        "collected_at": None,
                        "server_status": None,
                        "scheduler_status": None,
                        "dashboard_url": None,
                        "status_collection_state": str(
                            node.get("status_collection_state")
                            or STATUS_COLLECTION_NOT_COLLECTED
                        ),
                        "query_error": None,
                        "query_warning": None,
                        "job_count": 0,
                        "job_states": {},
                        "failed_job_count": 0,
                        "failed_job_ids": [],
                        "jobs": None,
                    },
                    "recovery": {
                        "resolved_lumi_action": "submit"
                        if node.get("planned_lumi_mask")
                        else None,
                        "resolved_lumi_source": node.get("planned_lumi_source"),
                        "resolved_lumi_mask": node.get("planned_lumi_mask"),
                        "submitted_at": node.get("submitted_at"),
                    },
                    "artifacts": {},
                }

    state = ensure_state_shape(state)
    write_json(state_path, state)
    return state


def load_state(
    state_path: Path, recovery_output_dir: Path | None = None
) -> dict[str, Any]:
    if state_needs_legacy_migration(state_path):
        return migrate_legacy_state(state_path, recovery_output_dir)
    return ensure_state_shape(load_json(state_path))


def find_attempt(state: dict[str, Any], task_dir: str) -> dict[str, Any]:
    try:
        return state["attempts"][task_dir]
    except KeyError as exc:
        raise KeyError(f"Task {task_dir} is not present in state file.") from exc


def positive_submit_times(job: dict[str, Any]) -> list[float]:
    return [float(value) for value in job.get("SubmitTimes", []) if value and value > 0]


def last_positive_submit_time(job: dict[str, Any]) -> float | None:
    submit_times = positive_submit_times(job)
    return max(submit_times) if submit_times else None


def classify_job_for_recovery(
    job: dict[str, Any], snapshot_time: datetime, stuck_hours: float
) -> tuple[bool, str | None]:
    state = str(job.get("State", "unknown"))
    if state == "unsubmitted":
        return True, None
    if state not in TIME_THRESHOLD_STATES:
        return False, None

    last_submit = last_positive_submit_time(job)
    if last_submit is None:
        return False, "missing-positive-submit-time"

    age_hours = (
        snapshot_time - datetime.fromtimestamp(last_submit, tz=timezone.utc)
    ).total_seconds() / 3600.0
    return age_hours >= stuck_hours, None


def count_states(jobs: dict[str, dict[str, Any]], job_ids: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job_id in job_ids:
        state = str(jobs[job_id].get("State", "unknown"))
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def normalize_attempt_config_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    units_per_job = metadata.get("units_per_job")
    if units_per_job is None:
        raise ValueError("config_metadata is missing units_per_job.")
    output_dataset_tag = metadata.get("output_dataset_tag")
    return {
        "units_per_job": int(units_per_job),
        "publication_enabled": bool(metadata.get("publication_enabled", False)),
        "output_dataset_tag": None
        if output_dataset_tag is None
        else str(output_dataset_tag),
    }


def load_cfg_metadata(cfg_path: Path) -> dict[str, Any]:
    metadata = load_cfg_metadata_via_literals(cfg_path)
    metadata.pop("parsed_config", None)
    return metadata


def merge_pycfg_params(
    base_params: list[Any], overrides: dict[str, Any]
) -> list[str]:
    override_map = {str(key): str(value) for key, value in overrides.items()}
    remaining = dict(override_map)
    merged: list[str] = []

    for item in base_params:
        item_text = str(item)
        if "=" in item_text:
            key, _value = item_text.split("=", 1)
            if key in override_map:
                merged.append(f"{key}={override_map[key]}")
                remaining.pop(key, None)
            else:
                merged.append(item_text)
        else:
            merged.append(item_text)

    for key, value in override_map.items():
        if key in remaining:
            merged.append(f"{key}={value}")

    return merged


def original_literal_config(cfg_path: Path) -> ParsedCrabConfig:
    return parse_literal_crab_config_file(cfg_path)


def cfg_field(
    parsed_config: ParsedCrabConfig,
    section: str,
    field_name: str,
    *,
    default: Any,
) -> Any:
    try:
        return parsed_config.get_field(section, field_name)
    except KeyError:
        return default


def build_recovery_replacements(
    attempt: dict[str, Any],
    parsed_config: ParsedCrabConfig,
    config_metadata: dict[str, Any],
    lumi_mask_path: Path,
) -> dict[str, str]:
    artifacts = attempt.get("artifacts", {})
    default_output_dataset_tag = (
        str(config_metadata["output_dataset_tag"])
        if bool(config_metadata["publication_enabled"])
        and config_metadata["output_dataset_tag"] is not None
        else str(artifacts["next_recover_request_name"])
    )
    default_pycfg_params = merge_pycfg_params(
        list(cfg_field(parsed_config, "JobType", "pyCfgParams", default=[])),
        DEFAULT_RECOVERY_PYCFG_PARAM_OVERRIDES,
    )
    return {
        "__REQUEST_NAME__": repr(str(artifacts["next_recover_request_name"])),
        "__RECOVERY_LUMI_MASK__": repr(str(lumi_mask_path)),
        "__DEFAULT_RECOVERY_UNITS_PER_JOB__": str(DEFAULT_RECOVERY_UNITS_PER_JOB),
        "__DEFAULT_RECOVERY_SPLITTING__": repr(
            str(cfg_field(parsed_config, "Data", "splitting", default="LumiBased"))
        ),
        "__DEFAULT_RECOVERY_OUTPUT_DATASET_TAG__": repr(default_output_dataset_tag),
        "__DEFAULT_RECOVERY_PYCFG_PARAMS__": repr(default_pycfg_params),
        "__DEFAULT_RECOVERY_NUM_CORES__": str(DEFAULT_RECOVERY_NUM_CORES),
        "__DEFAULT_RECOVERY_MAX_MEMORY_MB__": str(DEFAULT_RECOVERY_MAX_MEMORY_MB),
        "__DEFAULT_RECOVERY_PUBLICATION__": repr(
            bool(cfg_field(parsed_config, "Data", "publication", default=False))
        ),
        "__DEFAULT_RECOVERY_STORAGE_SITE__": repr(
            str(cfg_field(parsed_config, "Site", "storageSite", default=""))
        ),
    }


def build_attempt_config_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return normalize_attempt_config_metadata(
        {
            "units_per_job": metadata["units_per_job"],
            "publication_enabled": metadata["publication_enabled"],
            "output_dataset_tag": metadata["output_dataset_tag"],
        }
    )


def attempt_config_metadata(attempt: dict[str, Any]) -> dict[str, Any] | None:
    raw_metadata = attempt.get("config_metadata")
    if isinstance(raw_metadata, dict) and raw_metadata:
        return normalize_attempt_config_metadata(raw_metadata)

    legacy_units = attempt.get("original_units_per_job")
    if legacy_units is None:
        return None

    return normalize_attempt_config_metadata(
        {
            "units_per_job": legacy_units,
            "publication_enabled": attempt.get("publication_enabled", False),
            "output_dataset_tag": attempt.get("original_output_dataset_tag"),
        }
    )


def infer_status_collection_state(task: dict[str, Any]) -> str:
    state = str(task.get("status_collection_state") or "").strip()
    if state:
        return state
    if task.get("query_error"):
        if (
            str(task.get("server_status") or "").upper() == "KILLED"
            and "Could not locate JSON payload" in str(task.get("query_error"))
        ):
            return STATUS_COLLECTION_HEADER_ONLY_KILLED
        return STATUS_COLLECTION_FATAL_ERROR
    return STATUS_COLLECTION_OK


def json_file_nonempty(path: Path) -> bool:
    if not path.is_file():
        return False
    data = json.loads(path.read_text())
    return bool(data)


def normalize_local_lumi_path(
    raw_value: str, *, base_dir: Path | None = None
) -> Path:
    if raw_value.startswith(("http://", "https://")):
        raise ValueError(
            "URL-based lumi masks are not supported by recovery-chain validation."
        )
    path = Path(raw_value)
    if not path.is_absolute() and base_dir is not None:
        path = (base_dir / path).resolve()
    else:
        path = path.resolve()
    return path


def _is_compact_list_dict(value: dict[Any, Any]) -> bool:
    return all(
        isinstance(ranges, list)
        and all(
            isinstance(pair, (list, tuple))
            and len(pair) == 2
            and all(isinstance(item, int) for item in pair)
            for pair in ranges
        )
        for ranges in value.values()
    )


def _is_runs_and_lumis_dict(value: dict[Any, Any]) -> bool:
    return all(
        isinstance(lumis, list) and all(isinstance(item, int) for item in lumis)
        for lumis in value.values()
    )


def _is_run_lumi_pair_list(value: list[Any]) -> bool:
    return all(
        isinstance(item, (list, tuple))
        and len(item) == 2
        and all(isinstance(part, int) for part in item)
        for item in value
    )


def load_lumi_json_payload(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def lumi_list_from_value(value: Any, *, base_dir: Path | None = None) -> LumiList:
    if isinstance(value, LumiList):
        return value
    if isinstance(value, str):
        payload = load_lumi_json_payload(
            normalize_local_lumi_path(value, base_dir=base_dir)
        )
        return lumi_list_from_value(payload)
    if isinstance(value, dict):
        if _is_compact_list_dict(value):
            return LumiList(compactList=value)
        if _is_runs_and_lumis_dict(value):
            return LumiList(runsAndLumis=value)
        raise ValueError(f"Unsupported lumi-mask dict shape: {value!r}")
    if isinstance(value, list):
        if not _is_run_lumi_pair_list(value):
            raise ValueError("List lumi masks must be a list of [run, lumi] pairs.")
        return LumiList(lumis=value)
    raise ValueError(f"Unsupported lumi mask value: {value!r}")


def compact_lumi_dict(
    value: Any, *, base_dir: Path | None = None
) -> dict[str, list[list[int]]]:
    lumi_list = lumi_list_from_value(value, base_dir=base_dir)
    compact = lumi_list.getCompactList()
    return {
        str(run): [[int(pair[0]), int(pair[1])] for pair in ranges]
        for run, ranges in sorted(compact.items(), key=lambda item: int(item[0]))
    }


def normalize_state_lumi_mask(
    value: Any, *, base_dir: Path | None = None
) -> dict[str, list[list[int]]] | None:
    if value is None:
        return None
    return compact_lumi_dict(value, base_dir=base_dir)


def exact_same_lumis(
    left: Any,
    right: Any,
    *,
    left_base: Path | None = None,
    right_base: Path | None = None,
) -> bool:
    left_ll = LumiList(compactList=compact_lumi_dict(left, base_dir=left_base))
    right_ll = LumiList(compactList=compact_lumi_dict(right, base_dir=right_base))
    return not (left_ll - right_ll).getCompactList() and not (
        right_ll - left_ll
    ).getCompactList()


def processed_equals_planned(artifacts: dict[str, Any]) -> bool:
    processed = Path(str(artifacts.get("task_processed_lumis") or ""))
    planned = Path(str(artifacts.get("task_lumis_to_process") or ""))
    if not processed.is_file() or not planned.is_file():
        return False
    return exact_same_lumis(str(processed), str(planned))


def finished_job_count(attempt: dict[str, Any]) -> int:
    job_states = attempt.get("status", {}).get("job_states") or {}
    raw_value = job_states.get("finished", 0)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


def has_explicit_zero_finished_jobs(attempt: dict[str, Any]) -> bool:
    job_states = attempt.get("status", {}).get("job_states")
    if not isinstance(job_states, dict) or not job_states:
        return False
    return finished_job_count(attempt) == 0


def artifacts_for_attempt(
    state: dict[str, Any],
    attempt: dict[str, Any],
    output_dir: Path,
    recovery_suffix: str,
) -> dict[str, Any]:
    family = state["families"][attempt["family_id"]]
    root_attempt = state["attempts"][family["root_task_dir"]]
    root_request_name = str(root_attempt["request_name"])
    next_generation = len(family["attempt_order"])
    next_request_name = build_recovery_request_name(
        root_request_name, next_generation, recovery_suffix
    )
    crab_data_dir = Path(str(state["cwd"] or Path.cwd())).resolve()
    task_results_dir = (Path(attempt["task_path"]).resolve() / "results").resolve()
    report_dir = (output_dir / "reports" / attempt["task_dir"]).resolve()
    return {
        "task_results_dir": str(task_results_dir),
        "task_not_finished_lumis": str(
            (task_results_dir / "notFinishedLumis.json").resolve()
        ),
        "task_processed_lumis": str(
            (task_results_dir / "processedLumis.json").resolve()
        ),
        "task_lumis_to_process": str(
            (task_results_dir / "lumisToProcess.json").resolve()
        ),
        "report_dir": str(report_dir),
        "preserved_not_finished_lumis": str(
            (report_dir / "notFinishedLumis.json").resolve()
        ),
        "next_recover_request_name": next_request_name,
        "next_child_task_dir": f"crab_{next_request_name}",
        "next_child_task_path": str(
            (crab_data_dir / f"crab_{next_request_name}").resolve()
        ),
        "next_planned_lumi_mask_file": str(
            (output_dir / "lumimasks" / f"{next_request_name}.json").resolve()
        ),
        "next_recover_cfg": str(
            (output_dir / "configs" / f"{next_request_name}.py").resolve()
        ),
    }


def populate_attempt_metadata(state: dict[str, Any], attempt: dict[str, Any]) -> None:
    crab_data_dir = Path(str(state["cwd"] or Path.cwd())).resolve()
    cfg_path = resolve_cfg_path(crab_data_dir, str(attempt["cfg"]))
    attempt["cfg_path"] = str(cfg_path)
    config_metadata = attempt_config_metadata(attempt)
    needs_cfg_load = (
        config_metadata is None
        or attempt.get("original_lumi_mask") is None
        or not attempt.get("request_name")
    )
    if needs_cfg_load:
        try:
            metadata = load_cfg_metadata(cfg_path)
        except Exception:
            if config_metadata is None:
                raise
            attempt.setdefault("request_name", cfg_path.stem)
        else:
            attempt["request_name"] = metadata["request_name"]
            attempt["original_lumi_mask"] = normalize_state_lumi_mask(
                metadata["lumi_mask"], base_dir=cfg_path.parent
            )
            config_metadata = build_attempt_config_metadata(metadata)
    else:
        attempt["request_name"] = str(attempt.get("request_name") or cfg_path.stem)

    if config_metadata is None:
        raise ValueError(f"Missing effective config metadata for {cfg_path}.")

    attempt["config_metadata"] = config_metadata
    attempt["original_units_per_job"] = int(config_metadata["units_per_job"])
    attempt["publication_enabled"] = bool(config_metadata["publication_enabled"])
    attempt["original_output_dataset_tag"] = config_metadata["output_dataset_tag"]
    if int(attempt.get("generation", 0)) == 0 and not attempt.get(
        "planned_lumi_mask"
    ):
        attempt["planned_lumi_mask"] = attempt["original_lumi_mask"]
        attempt["planned_lumi_source"] = "original_task_lumi_mask"


def clear_stale_resolution(recovery: dict[str, Any]) -> None:
    recovery["resolved_lumi_action"] = None
    recovery["resolved_lumi_source"] = None
    recovery["resolved_lumi_mask"] = None


def derive_recovery_for_attempt(
    state: dict[str, Any],
    attempt: dict[str, Any],
    output_dir: Path,
    stuck_hours: float,
    recovery_suffix: str,
) -> None:
    status = attempt.get("status", {})
    status_collection_state = str(
        status.get("status_collection_state") or STATUS_COLLECTION_NOT_COLLECTED
    )
    snapshot_time = parse_snapshot_time(
        str(status.get("collected_at") or state.get("updated_at") or now_iso())
    )
    server_status = str(status.get("server_status") or "")
    scheduler_status = str(status.get("scheduler_status") or "")
    jobs = status.get("jobs") or {}
    if not isinstance(jobs, dict):
        jobs = {}

    recovery_job_ids: list[str] = []
    skipped_jobs_without_time: list[str] = []
    for job_id, job in sorted(jobs.items(), key=lambda item: int(item[0])):
        should_recover, reason = classify_job_for_recovery(
            job, snapshot_time, stuck_hours
        )
        if should_recover:
            recovery_job_ids.append(str(job_id))
        elif reason == "missing-positive-submit-time":
            skipped_jobs_without_time.append(str(job_id))

    recovery_job_id_set = set(recovery_job_ids)
    blocking_job_ids: list[str] = []
    for job_id, job in sorted(jobs.items(), key=lambda item: int(item[0])):
        if job_id in recovery_job_id_set:
            continue
        if str(job.get("State", "unknown")) in NON_FINISHED_STATES:
            blocking_job_ids.append(str(job_id))

    hold_age = hold_age_hours(status, snapshot_time)
    if (
        hold_age is None
        and is_holding_resubmit_server_status(server_status)
        and status.get("collected_at")
    ):
        hold_age = 0.0

    if status_collection_state == STATUS_COLLECTION_FATAL_ERROR:
        classification = "query_error"
    elif is_killed_server_status(server_status):
        if scheduler_status.strip().upper() == "COMPLETED":
            classification = "no_action"
        else:
            classification = "killed_recovery_candidate"
    elif is_holding_resubmit_server_status(server_status):
        if hold_age is not None and hold_age >= stuck_hours:
            classification = "holding_resubmit_recovery_candidate"
        else:
            classification = "holding_resubmit_pending"
    elif recovery_job_ids and blocking_job_ids:
        classification = "mixed"
    elif recovery_job_ids:
        classification = "recovery_candidate"
    elif int(status.get("failed_job_count", 0)):
        classification = "failed_only"
    else:
        classification = "no_action"

    recovery = attempt.setdefault("recovery", {})
    if recovery.get("derived_from_revision") != attempt.get("status_revision"):
        clear_stale_resolution(recovery)

    has_child_attempt = get_latest_task(state, str(attempt["task_dir"])) != str(
        attempt["task_dir"]
    )

    recovery.update(
        {
            "classification": classification,
            "recovery_job_ids": recovery_job_ids,
            "recovery_state_counts": count_states(jobs, recovery_job_id_set),
            "blocking_job_ids": blocking_job_ids,
            "blocking_state_counts": count_states(jobs, set(blocking_job_ids)),
            "skipped_jobs_without_time": skipped_jobs_without_time,
            "kill_required": classification != "killed_recovery_candidate"
            and not is_killed_server_status(server_status),
            "hold_age_hours": hold_age,
            "derived_from_revision": attempt.get("status_revision"),
            "has_child_attempt": has_child_attempt,
            "executable": (not has_child_attempt)
            and classification in RECOVERY_RENDER_CLASSES,
            "submitted_child_attempt_id": recovery.get("submitted_child_attempt_id"),
            "submitted_at": recovery.get("submitted_at"),
        }
    )
    attempt["artifacts"] = artifacts_for_attempt(
        state, attempt, output_dir, recovery_suffix
    )


def refresh_recovery_state(args: argparse.Namespace) -> int:
    state_path = resolve_state_file_arg(args).resolve()
    output_dir = Path(args.output_dir).resolve()
    state = load_state(state_path, output_dir)
    state["stuck_hours"] = float(args.stuck_hours)
    state["recovery_suffix"] = str(args.recovery_suffix)
    rebuild_families(state)

    for attempt in state["attempts"].values():
        populate_attempt_metadata(state, attempt)
    rebuild_families(state)

    query_failures: list[str] = []
    header_only_killed_tasks: list[str] = []
    counts = {
        "recovery_candidate": 0,
        "mixed": 0,
        "killed_recovery_candidate": 0,
        "holding_resubmit_recovery_candidate": 0,
        "holding_resubmit_pending": 0,
        "failed_only": 0,
        "no_action": 0,
        "query_error": 0,
    }
    for attempt in state["attempts"].values():
        derive_recovery_for_attempt(
            state,
            attempt,
            output_dir,
            float(args.stuck_hours),
            str(args.recovery_suffix),
        )
        classification = str(attempt["recovery"]["classification"])
        counts[classification] = counts.get(classification, 0) + 1
        status_state = str(attempt["status"].get("status_collection_state") or "")
        if status_state == STATUS_COLLECTION_FATAL_ERROR:
            query_failures.append(str(attempt["task_dir"]))
        elif status_state == STATUS_COLLECTION_HEADER_ONLY_KILLED:
            header_only_killed_tasks.append(str(attempt["task_dir"]))

    state["query_failures"] = sorted(query_failures)
    state["header_only_killed_tasks"] = sorted(header_only_killed_tasks)
    state["recovery_counts"] = counts
    state["updated_at"] = now_iso()
    write_json(state_path, state)

    if query_failures:
        raise RuntimeError(
            "Status snapshot still contains fatal query failures: "
            + ", ".join(query_failures)
        )

    print(
        "Refreshed recovery metadata: "
        f"recovery={counts['recovery_candidate']} "
        f"killed={counts['killed_recovery_candidate']} "
        f"holding_recovery={counts['holding_resubmit_recovery_candidate']} "
        f"holding_pending={counts['holding_resubmit_pending']} "
        f"mixed={counts['mixed']} "
        f"failed_only={counts['failed_only']} "
        f"no_action={counts['no_action']}"
    )
    return 0


def ensure_recovery_current(state: dict[str, Any]) -> None:
    stale: list[str] = []
    for attempt_id, attempt in state["attempts"].items():
        status_revision = attempt.get("status_revision")
        recovery_revision = attempt.get("recovery", {}).get("derived_from_revision")
        if status_revision and recovery_revision != status_revision:
            stale.append(str(attempt_id))
    if stale:
        raise RuntimeError(
            "Recovery metadata is stale for: "
            + ", ".join(sorted(stale))
            + ". Run crab_recovery_task_builder.py refresh-recovery first."
        )


def resolve_lumi_for_attempt(
    attempt: dict[str, Any], runtime_server_status: str | None = None
) -> tuple[str, str, Any]:
    artifacts = attempt.get("artifacts", {})
    preserved = Path(
        str(artifacts.get("preserved_not_finished_lumis") or "")
    ).resolve()
    task_not_finished = Path(
        str(artifacts.get("task_not_finished_lumis") or "")
    ).resolve()
    planned_lumi_mask = attempt.get("planned_lumi_mask") or attempt.get(
        "original_lumi_mask"
    )

    if json_file_nonempty(preserved):
        return "submit", "preserved_not_finished", compact_lumi_dict(str(preserved))
    if preserved.is_file():
        return "skip", "no_not_finished_lumis", ""

    if json_file_nonempty(task_not_finished):
        return "submit", "task_results_not_finished", compact_lumi_dict(
            str(task_not_finished)
        )
    if task_not_finished.is_file():
        return "skip", "no_not_finished_lumis", ""

    if processed_equals_planned(artifacts):
        return "skip", "complete", ""

    classification = str(attempt.get("recovery", {}).get("classification") or "")
    normalized_runtime_status = (runtime_server_status or "").strip().upper()
    if (
        classification == "killed_recovery_candidate"
        or normalized_runtime_status == "KILLED"
    ) and planned_lumi_mask:
        return "submit", "parent_planned_lumi_mask_killed", planned_lumi_mask

    if has_explicit_zero_finished_jobs(attempt) and planned_lumi_mask:
        return "submit", "parent_planned_lumi_mask_no_finished_jobs", planned_lumi_mask

    return "error", "missing_not_finished_lumis", ""


def write_compact_lumi_mask_file(
    compact_mask: dict[str, list[list[int]]], output_path: Path
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(compact_mask, indent=2, sort_keys=True) + "\n")
    return output_path


def render_recovery_config(attempt: dict[str, Any], template_path: Path) -> Path:
    cfg_path = Path(str(attempt["cfg_path"])).resolve()
    config_metadata = attempt_config_metadata(attempt)
    if config_metadata is None:
        config_metadata = build_attempt_config_metadata(load_cfg_metadata(cfg_path))
    parsed_original = original_literal_config(cfg_path)
    recovery = attempt.get("recovery", {})
    artifacts = attempt.get("artifacts", {})

    compact_mask = recovery.get("resolved_lumi_mask")
    if compact_mask is None:
        resolve_action, resolve_source, compact_mask = resolve_lumi_for_attempt(attempt)
        if resolve_action != "submit" or not compact_mask:
            raise RuntimeError(
                f"Task {attempt['task_dir']} has no resolved recovery lumi mask; "
                f"lumi resolution returned {resolve_action}:{resolve_source}."
            )
    lumi_mask_path = write_compact_lumi_mask_file(
        compact_mask, Path(str(artifacts["next_planned_lumi_mask_file"])).resolve()
    )
    replacements = build_recovery_replacements(
        attempt, parsed_original, config_metadata, lumi_mask_path
    )
    rendered = render_template(template_path.read_text(), replacements)

    unresolved = sorted(set(re.findall(r"__[A-Z0-9_]+__", rendered)))
    if unresolved:
        raise ValueError(
            "Unresolved placeholders in rendered recovery config for "
            f"{cfg_path}: {unresolved}"
        )

    parsed_template = parse_literal_crab_config(rendered, source_name=str(template_path))
    merged = merge_literal_assignments(parsed_original, parsed_template)
    output_path = Path(str(artifacts["next_recover_cfg"])).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(emit_wmcore_crab_config(merged))
    return output_path


def render_one(args: argparse.Namespace) -> int:
    state_path = resolve_state_file_arg(args).resolve()
    state = load_state(state_path)
    ensure_recovery_current(state)
    attempt = find_attempt(state, args.task)

    if not attempt.get("recovery", {}).get("executable", False):
        raise RuntimeError(
            f"Task {attempt['task_dir']} is not currently executable for recovery."
        )

    template_path = Path(__file__).with_name("crab3_recovery_template.py")
    output_path = render_recovery_config(attempt, template_path)
    print(output_path)
    return 0


def render_all(args: argparse.Namespace) -> int:
    state_path = resolve_state_file_arg(args).resolve()
    state = load_state(state_path)
    ensure_recovery_current(state)
    rendered_paths: list[str] = []
    template_path = Path(__file__).with_name("crab3_recovery_template.py")

    for attempt in state["attempts"].values():
        if not attempt.get("recovery", {}).get("executable", False):
            continue
        rendered_paths.append(str(render_recovery_config(attempt, template_path)))

    output_dir = Path("recovery_cache").resolve()
    if state["attempts"]:
        any_attempt = next(iter(state["attempts"].values()))
        artifacts = any_attempt.get("artifacts", {})
        if artifacts.get("next_recover_cfg"):
            output_dir = Path(str(artifacts["next_recover_cfg"])).resolve().parent.parent
    manifest_path = output_dir / CONFIG_MANIFEST_NAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        "\n".join(rendered_paths) + ("\n" if rendered_paths else "")
    )
    print(f"Rendered {len(rendered_paths)} recovery config(s)")
    print(manifest_path)
    return 0


def load_cfg_lumi_mask(cfg_path: Path) -> Any:
    return load_cfg_metadata(cfg_path)["lumi_mask"]


def load_cfg_request_name(cfg_path: Path) -> str:
    return str(load_cfg_metadata(cfg_path)["request_name"])


def expected_child_lumi_mask(attempt: dict[str, Any]) -> tuple[str, Any | None]:
    artifacts = attempt.get("artifacts", {})
    preserved = Path(str(artifacts.get("preserved_not_finished_lumis") or "")).resolve()
    task_local = Path(str(artifacts.get("task_not_finished_lumis") or "")).resolve()

    if json_file_nonempty(preserved):
        return "preserved_not_finished", compact_lumi_dict(str(preserved))
    if json_file_nonempty(task_local):
        return "task_results_not_finished", compact_lumi_dict(str(task_local))
    if processed_equals_planned(artifacts):
        return "complete", None
    if (
        str(attempt.get("recovery", {}).get("classification") or "")
        == "killed_recovery_candidate"
        or has_explicit_zero_finished_jobs(attempt)
    ):
        planned = attempt.get("planned_lumi_mask")
        if planned:
            return "parent_planned_lumi_mask_fallback", planned
    raise RuntimeError("Cannot validate child recovery coverage")


def validate_child_coverage_against_parent(
    attempt: dict[str, Any], child_lumi_mask: Any, *, child_base_dir: Path
) -> str:
    source, expected = expected_child_lumi_mask(attempt)
    if source == "complete":
        raise RuntimeError("Parent attempt is already complete; no child may be chained.")
    if not exact_same_lumis(expected, child_lumi_mask, right_base=child_base_dir):
        raise RuntimeError(
            f"Child lumi mask does not exactly match parent missing coverage ({source})."
        )
    return source


def child_append_spec(
    attempt: dict[str, Any],
    *,
    child_task_dir: str,
    child_cfg_path: Path,
    child_task_path: Path,
    child_request_name: str,
    child_lumi_mask: Any,
    child_cfg_metadata: dict[str, Any],
    planned_lumi_source: str | None = None,
) -> ChainAppendSpec:
    config_metadata = build_attempt_config_metadata(child_cfg_metadata)
    return ChainAppendSpec(
        task_dir=child_task_dir,
        cfg_path=str(child_cfg_path.resolve()),
        task_path=str(child_task_path.resolve()),
        request_name=child_request_name,
        planned_lumi_mask=compact_lumi_dict(
            child_lumi_mask, base_dir=child_cfg_path.parent
        ),
        planned_lumi_source=str(
            planned_lumi_source
            or attempt.get("recovery", {}).get("resolved_lumi_source")
            or attempt.get("planned_lumi_source")
            or "manual_chain"
        ),
        original_lumi_mask=normalize_state_lumi_mask(
            child_cfg_metadata.get("lumi_mask"), base_dir=child_cfg_path.parent
        ),
        original_units_per_job=int(config_metadata["units_per_job"]),
        publication_enabled=bool(config_metadata["publication_enabled"]),
        original_output_dataset_tag=config_metadata["output_dataset_tag"],
        config_metadata=config_metadata,
    )


def list_executable(args: argparse.Namespace) -> int:
    state_path = resolve_state_file_arg(args).resolve()
    state = load_state(state_path)
    ensure_recovery_current(state)
    include_classes = {
        "recovery_candidate",
        "killed_recovery_candidate",
        "holding_resubmit_recovery_candidate",
    }
    if args.include_mixed:
        include_classes.add("mixed")

    for attempt in state["attempts"].values():
        recovery = attempt.get("recovery", {})
        if not recovery.get("executable", False):
            continue
        if recovery.get("classification") not in include_classes:
            continue
        artifacts = attempt.get("artifacts", {})
        print(
            "\t".join(
                [
                    str(attempt["task_dir"]),
                    str(attempt["task_path"]),
                    str(artifacts["report_dir"]),
                    str(artifacts["preserved_not_finished_lumis"]),
                    str(artifacts["next_recover_cfg"]),
                    str(recovery["classification"]),
                ]
            )
        )
    return 0


def resolve_lumi_mask(args: argparse.Namespace) -> int:
    state_path = resolve_state_file_arg(args).resolve()
    state = load_state(state_path)
    ensure_recovery_current(state)
    attempt = find_attempt(state, args.task)

    if not attempt.get("recovery", {}).get("executable", False):
        raise RuntimeError(
            f"Task {attempt['task_dir']} is not currently executable for recovery."
        )

    action, source, path = resolve_lumi_for_attempt(
        attempt, getattr(args, "runtime_server_status", None)
    )
    attempt.setdefault("recovery", {})["resolved_lumi_action"] = action
    attempt["recovery"]["resolved_lumi_source"] = source
    attempt["recovery"]["resolved_lumi_mask"] = path or None
    state["updated_at"] = now_iso()
    write_json(state_path, state)
    output = ""
    if isinstance(path, str):
        output = path
    elif path:
        output = json.dumps(path, sort_keys=True)
    print("\t".join([action, source, output]))
    return 0


def record_submission(args: argparse.Namespace) -> int:
    state_path = resolve_state_file_arg(args).resolve()
    state = load_state(state_path)
    ensure_recovery_current(state)
    attempt = find_attempt(state, args.task)
    recovery = attempt.get("recovery", {})

    if not recovery.get("executable", False):
        raise RuntimeError(
            f"Task {attempt['task_dir']} is not currently executable for recovery."
        )
    if recovery.get("resolved_lumi_action") != "submit" or not recovery.get(
        "resolved_lumi_mask"
    ):
        raise RuntimeError(
            f"Task {attempt['task_dir']} has no resolved recovery lumi mask; run resolve-lumi-mask first."
        )

    if recovery.get("submitted_child_attempt_id"):
        raise RuntimeError(
            f"Task {attempt['task_dir']} already recorded child {recovery['submitted_child_attempt_id']}."
        )

    artifacts = attempt["artifacts"]
    child_task_dir = str(artifacts["next_child_task_dir"])
    child_cfg_path = Path(str(artifacts["next_recover_cfg"])).resolve()
    child_cfg_metadata = load_cfg_metadata(child_cfg_path)
    child_spec = child_append_spec(
        attempt,
        child_task_dir=child_task_dir,
        child_cfg_path=child_cfg_path,
        child_task_path=Path(str(artifacts["next_child_task_path"])),
        child_request_name=str(artifacts["next_recover_request_name"]),
        child_lumi_mask=recovery["resolved_lumi_mask"],
        child_cfg_metadata=child_cfg_metadata,
    )
    append_after(
        state,
        str(attempt["task_dir"]),
        child_spec,
        status_collection_state=STATUS_COLLECTION_NOT_COLLECTED,
    )
    recovery["submitted_child_attempt_id"] = child_task_dir
    recovery["submitted_at"] = now_iso()
    state["updated_at"] = now_iso()
    write_json(state_path, state)
    print(child_task_dir)
    print(state_path)
    return 0


def add_to_chain(args: argparse.Namespace) -> int:
    state_path = resolve_state_file_arg(args).resolve()
    state = load_state(state_path)
    ensure_recovery_current(state)
    rebuild_families(state)

    attempt = find_attempt(state, args.parent_task)
    child_cfg_path = Path(args.child_cfg).resolve()
    child_cfg_metadata = load_cfg_metadata(child_cfg_path)
    child_lumi_mask = child_cfg_metadata["lumi_mask"]
    child_request_name = str(child_cfg_metadata["request_name"])
    source = validate_child_coverage_against_parent(
        attempt, child_lumi_mask, child_base_dir=child_cfg_path.parent
    )
    child_task_path = (
        Path(args.child_task_path).resolve()
        if args.child_task_path
        else (Path(str(state.get("cwd") or Path.cwd())).resolve() / args.child_task_dir)
    )
    child_spec = child_append_spec(
        attempt,
        child_task_dir=str(args.child_task_dir),
        child_cfg_path=child_cfg_path,
        child_task_path=child_task_path,
        child_request_name=child_request_name,
        child_lumi_mask=child_lumi_mask,
        child_cfg_metadata=child_cfg_metadata,
        planned_lumi_source=source,
    )
    append_after(
        state,
        str(attempt["task_dir"]),
        child_spec,
        status_collection_state=STATUS_COLLECTION_NOT_COLLECTED,
    )
    state["updated_at"] = now_iso()
    write_json(state_path, state)
    print(child_spec.task_dir)
    print(state_path)
    print(source)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ensure_cmssw_env()
    if args.command in {"refresh-recovery", "plan"}:
        return refresh_recovery_state(args)
    if args.command == "render-one":
        return render_one(args)
    if args.command == "render-all":
        return render_all(args)
    if args.command == "list-executable":
        return list_executable(args)
    if args.command == "resolve-lumi-mask":
        return resolve_lumi_mask(args)
    if args.command == "record-submission":
        return record_submission(args)
    if args.command == "add-to-chain":
        return add_to_chain(args)
    raise ValueError(f"Unknown command {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI error reporting
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
