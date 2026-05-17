#!/usr/bin/env python3
"""Compatibility wrapper for the unified recovery state builder."""

from crab_recovery_state_builder import *  # noqa: F401,F403
from crab_recovery_state_builder import main as state_builder_main


if __name__ == "__main__":
    raise SystemExit(state_builder_main())

'''
"""Build recovery plans, lineage metadata, and recovery configs for CRAB tasks."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
PLAN_NAME = "latest_recovery_plan.json"
CONFIG_MANIFEST_NAME = "generated_recovery_configs.txt"
LINEAGE_NAME = "task_lineage.json"
TRACKED_CONFIGS_NAME = "tracked_configs.txt"
STATUS_COLLECTION_OK = "ok_json"
STATUS_COLLECTION_HEADER_ONLY_KILLED = "header_only_killed"
STATUS_COLLECTION_FATAL_ERROR = "fatal_error"
STATUS_COLLECTION_NOT_COLLECTED = "not_collected"
RECOVERY_RENDER_CLASSES = {"recovery_candidate", "mixed", "killed_recovery_candidate"}


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare recovery-task metadata, keep recovery lineage, and render CRAB "
            "recovery configs."
        ),
        formatter_class=HelpFormatter,
        epilog=(
            "Examples:\n"
            "  crab_recovery_task_builder.py plan --summary-file status_cache/latest_summary.json\n"
            "  crab_recovery_task_builder.py resolve-lumi-mask --plan-file recovery_cache/latest_recovery_plan.json --task crab_task\n"
            "  crab_recovery_task_builder.py record-submission --plan-file recovery_cache/latest_recovery_plan.json --task crab_task\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser(
        "plan",
        help="Build a recovery plan from a cached CRAB status snapshot.",
        description=(
            "Read a cached CRAB status snapshot, classify each task, and write a "
            "recovery plan plus lineage metadata."
        ),
        formatter_class=HelpFormatter,
        epilog=(
            "Output files:\n"
            "  <output-dir>/latest_recovery_plan.json\n"
            "  <output-dir>/task_lineage.json\n"
            "  <output-dir>/tracked_configs.txt"
        ),
    )
    plan_parser.add_argument(
        "--summary-file",
        default="status_cache/latest_summary.json",
        help="Status summary file produced by crab_status_snapshot.py collect.",
    )
    plan_parser.add_argument(
        "--output-dir",
        default="recovery_cache",
        help="Directory where the recovery plan, lineage, and rendered configs are written.",
    )
    plan_parser.add_argument(
        "--stuck-hours",
        type=float,
        default=DEFAULT_STUCK_HOURS,
        help="Minimum idle/cooloff age required to classify a job for recovery.",
    )
    plan_parser.add_argument(
        "--recovery-suffix",
        default=RECOVERY_SUFFIX,
        help="Suffix family used for generated recovery request names.",
    )

    render_parser = subparsers.add_parser(
        "render-one",
        help="Render one recovery CRAB config from a saved recovery plan.",
        formatter_class=HelpFormatter,
    )
    render_parser.add_argument(
        "--plan-file",
        default=f"recovery_cache/{PLAN_NAME}",
        help="Recovery plan JSON file produced by the plan subcommand.",
    )
    render_parser.add_argument(
        "--task",
        required=True,
        help="Task directory name to render, for example crab_my_task.",
    )

    render_all_parser = subparsers.add_parser(
        "render-all",
        help="Render recovery configs for every executable task in a saved recovery plan.",
        formatter_class=HelpFormatter,
        epilog=(
            "Output files:\n"
            "  <output-dir>/configs/*.py\n"
            "  <output-dir>/generated_recovery_configs.txt"
        ),
    )
    render_all_parser.add_argument(
        "--plan-file",
        default=f"recovery_cache/{PLAN_NAME}",
        help="Recovery plan JSON file produced by the plan subcommand.",
    )

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
    list_parser.add_argument(
        "--plan-file",
        default=f"recovery_cache/{PLAN_NAME}",
        help="Recovery plan JSON file produced by the plan subcommand.",
    )
    list_parser.add_argument(
        "--include-mixed",
        action="store_true",
        help="Also list tasks classified as mixed in the recovery plan.",
    )

    resolve_parser = subparsers.add_parser(
        "resolve-lumi-mask",
        help="Resolve the lumi mask that a recovery config should use.",
        formatter_class=HelpFormatter,
        epilog=(
            "Output columns:\n"
            "  action<TAB>source<TAB>path\n\n"
            "The plan file is updated in place with resolved_lumi_mask and "
            "resolved_lumi_source."
        ),
    )
    resolve_parser.add_argument(
        "--plan-file",
        default=f"recovery_cache/{PLAN_NAME}",
        help="Recovery plan JSON file produced by the plan subcommand.",
    )
    resolve_parser.add_argument(
        "--task",
        required=True,
        help="Task directory name to resolve, for example crab_my_task.",
    )

    record_parser = subparsers.add_parser(
        "record-submission",
        help="Record a successfully submitted recovery child in the lineage DAG.",
        formatter_class=HelpFormatter,
        epilog=(
            "Output files updated:\n"
            "  <output-dir>/task_lineage.json\n"
            "  <output-dir>/tracked_configs.txt"
        ),
    )
    record_parser.add_argument(
        "--plan-file",
        default=f"recovery_cache/{PLAN_NAME}",
        help="Recovery plan JSON file produced by the plan subcommand.",
    )
    record_parser.add_argument(
        "--task",
        required=True,
        help="Parent task directory that just spawned a recovery child.",
    )

    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}.")
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def parse_snapshot_time(raw: str) -> datetime:
    return datetime.fromisoformat(raw)


def resolve_cfg_path(crab_data_dir: Path, cfg: str) -> Path:
    cfg_path = Path(cfg)
    if cfg_path.is_absolute():
        return cfg_path.resolve()
    return (crab_data_dir / cfg_path).resolve()


def task_payload_path(summary_file: Path, task_status_file: str) -> Path:
    return summary_file.parent / task_status_file


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


def extract_assignment(text: str, key: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def ast_literal_eval(expr: str, cfg_path: Path, label: str) -> Any:
    import ast

    try:
        return ast.literal_eval(expr)
    except Exception as exc:
        raise ValueError(f"Could not parse {label} from {cfg_path}: {exc}") from exc


def parse_original_cfg_metadata(cfg_path: Path) -> dict[str, Any]:
    text = cfg_path.read_text()

    units_expr = extract_assignment(text, "config.Data.unitsPerJob")
    if units_expr is None:
        raise ValueError(f"Could not parse config.Data.unitsPerJob from {cfg_path}.")

    publication_expr = extract_assignment(text, "config.Data.publication")
    output_dataset_tag_expr = extract_assignment(text, "config.Data.outputDatasetTag")
    lumi_mask_expr = extract_assignment(text, "config.Data.lumiMask")

    publication_enabled = False
    if publication_expr is not None:
        publication_enabled = bool(
            ast_literal_eval(publication_expr, cfg_path, "config.Data.publication")
        )

    output_dataset_tag = None
    if output_dataset_tag_expr is not None:
        output_dataset_tag = ast_literal_eval(
            output_dataset_tag_expr, cfg_path, "config.Data.outputDatasetTag"
        )

    lumi_mask = None
    if lumi_mask_expr is not None:
        lumi_mask = ast_literal_eval(lumi_mask_expr, cfg_path, "config.Data.lumiMask")

    units_per_job = ast_literal_eval(units_expr, cfg_path, "config.Data.unitsPerJob")
    return {
        "units_per_job": int(units_per_job),
        "publication_enabled": publication_enabled,
        "output_dataset_tag": output_dataset_tag,
        "lumi_mask": lumi_mask,
    }


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


def load_lineage(path: Path) -> dict[str, Any]:
    if path.exists():
        lineage = load_json(path)
        lineage.setdefault("nodes", {})
        lineage.setdefault("edges", [])
        return lineage
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "nodes": {},
        "edges": [],
    }


def lineage_node_for_request(
    lineage: dict[str, Any], request_name: str
) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    for task_dir, node in lineage.get("nodes", {}).items():
        if str(node.get("request_name")) == request_name:
            return task_dir, node
    return None, None


def infer_parent_task_dir(
    lineage: dict[str, Any], root_request_name: str, generation: int
) -> str | None:
    if generation <= 0:
        return None
    candidates: list[str] = []
    for task_dir, node in lineage.get("nodes", {}).items():
        if (
            str(node.get("root_request_name")) == root_request_name
            and int(node.get("generation", -1)) == generation - 1
        ):
            candidates.append(task_dir)
    if len(candidates) == 1:
        return candidates[0]
    return None


def json_file_nonempty(path: Path) -> bool:
    if not path.is_file():
        return False
    data = json.loads(path.read_text())
    return bool(data)


def normalize_lumi_mask_value(raw_value: str) -> str:
    if "://" in raw_value:
        return raw_value
    return str(Path(raw_value).resolve())


def add_lineage_edge(lineage: dict[str, Any], parent: str, child: str) -> None:
    for edge in lineage.get("edges", []):
        if edge.get("parent") == parent and edge.get("child") == child:
            return
    lineage.setdefault("edges", []).append(
        {
            "parent": parent,
            "child": child,
            "reason": "recovery",
        }
    )


def update_current_nodes_in_lineage(
    lineage: dict[str, Any], entries: list[dict[str, Any]]
) -> None:
    nodes = lineage.setdefault("nodes", {})
    for entry in entries:
        node = dict(nodes.get(entry["task_dir"], {}))
        node.update(
            {
                "task_dir": entry["task_dir"],
                "task_path": entry["task_path"],
                "cfg": entry["cfg"],
                "cfg_path": entry["cfg_path"],
                "request_name": entry["request_name"],
                "root_request_name": entry["root_request_name"],
                "generation": entry["generation"],
                "parent_task_dir": entry["parent_task_dir"],
                "server_status": entry["server_status"],
                "scheduler_status": entry["scheduler_status"],
                "status_collection_state": entry["status_collection_state"],
                "original_lumi_mask": entry["original_lumi_mask"],
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        nodes[entry["task_dir"]] = node
        if entry["parent_task_dir"]:
            add_lineage_edge(lineage, entry["parent_task_dir"], entry["task_dir"])


def lineage_nodes_in_order(lineage: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = list(lineage.get("nodes", {}).values())
    return sorted(
        nodes,
        key=lambda node: (
            str(node.get("root_request_name") or node.get("request_name") or ""),
            int(node.get("generation", 0)),
            str(node.get("request_name") or ""),
        ),
    )


def write_tracked_manifest(lineage: dict[str, Any], output_dir: Path) -> Path:
    lines: list[str] = []
    for node in lineage_nodes_in_order(lineage):
        cfg_path = str(node.get("cfg_path") or "")
        task_path = str(node.get("task_path") or "")
        if not cfg_path:
            continue
        if task_path and not Path(task_path).exists():
            continue
        if cfg_path not in lines:
            lines.append(cfg_path)
    manifest_path = output_dir / TRACKED_CONFIGS_NAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("\n".join(lines) + ("\n" if lines else ""))
    return manifest_path


def build_task_entry(
    task: dict[str, Any],
    jobs: dict[str, dict[str, Any]] | None,
    snapshot_time: datetime,
    crab_data_dir: Path,
    output_dir: Path,
    stuck_hours: float,
    recovery_suffix: str,
    lineage: dict[str, Any],
) -> dict[str, Any]:
    task_dir = str(task["task_dir"])
    cfg = str(task["cfg"])
    cfg_path = resolve_cfg_path(crab_data_dir, cfg)
    cfg_metadata = parse_original_cfg_metadata(cfg_path)
    request_name = cfg_path.stem

    existing_node = lineage.get("nodes", {}).get(task_dir)
    if existing_node:
        root_request_name = str(existing_node.get("root_request_name") or request_name)
        generation = int(existing_node.get("generation", 0))
        parent_task_dir = existing_node.get("parent_task_dir")
    else:
        lineage_task_dir, lineage_node = lineage_node_for_request(lineage, request_name)
        if lineage_node is not None and lineage_task_dir is not None:
            root_request_name = str(lineage_node.get("root_request_name") or request_name)
            generation = int(lineage_node.get("generation", 0))
            parent_task_dir = lineage_node.get("parent_task_dir")
        else:
            root_request_name, generation = infer_request_lineage(
                request_name, recovery_suffix
            )
            parent_task_dir = infer_parent_task_dir(lineage, root_request_name, generation)

    child_generation = generation + 1
    recover_request_name = build_recovery_request_name(
        root_request_name, child_generation, recovery_suffix
    )
    child_task_dir = f"crab_{recover_request_name}"
    child_task_path = (crab_data_dir / child_task_dir).resolve()
    task_results_dir = (Path(task["task_path"]).resolve() / "results").resolve()
    task_not_finished_lumis = (task_results_dir / "notFinishedLumis.json").resolve()
    report_dir = (output_dir / "reports" / task_dir).resolve()
    preserved_not_finished_lumis = (report_dir / "notFinishedLumis.json").resolve()
    report_processed_lumis = (report_dir / "processedLumis.json").resolve()
    recover_cfg = (output_dir / "configs" / f"{recover_request_name}.py").resolve()
    status_collection_state = infer_status_collection_state(task)

    job_map = jobs or {}
    recovery_job_ids: list[str] = []
    skipped_jobs_without_time: list[str] = []
    for job_id, job in sorted(job_map.items(), key=lambda item: int(item[0])):
        should_recover, reason = classify_job_for_recovery(job, snapshot_time, stuck_hours)
        if should_recover:
            recovery_job_ids.append(str(job_id))
        elif reason == "missing-positive-submit-time":
            skipped_jobs_without_time.append(str(job_id))

    recovery_job_id_set = set(recovery_job_ids)
    blocking_job_ids: list[str] = []
    for job_id, job in sorted(job_map.items(), key=lambda item: int(item[0])):
        if job_id in recovery_job_id_set:
            continue
        if str(job.get("State", "unknown")) in NON_FINISHED_STATES:
            blocking_job_ids.append(str(job_id))

    if status_collection_state == STATUS_COLLECTION_FATAL_ERROR:
        classification = "query_error"
    elif status_collection_state == STATUS_COLLECTION_HEADER_ONLY_KILLED:
        classification = "killed_recovery_candidate"
    elif recovery_job_ids and blocking_job_ids:
        classification = "mixed"
    elif recovery_job_ids:
        classification = "recovery_candidate"
    elif task.get("failed_job_count", 0):
        classification = "failed_only"
    else:
        classification = "no_action"

    return {
        "cfg": cfg,
        "cfg_path": str(cfg_path),
        "task_dir": task_dir,
        "task_path": str(Path(task["task_path"]).resolve()),
        "task_name": task.get("task_name"),
        "task_status_file": str(task.get("task_status_file", "")),
        "dashboard_url": task.get("dashboard_url"),
        "server_status": task.get("server_status"),
        "scheduler_status": task.get("scheduler_status"),
        "job_count": int(task.get("job_count", 0)),
        "job_states": task.get("job_states", {}),
        "failed_job_count": int(task.get("failed_job_count", 0)),
        "failed_job_ids": [str(job_id) for job_id in task.get("failed_job_ids", [])],
        "status_collection_state": status_collection_state,
        "query_error": task.get("query_error"),
        "query_warning": task.get("query_warning"),
        "classification": classification,
        "request_name": request_name,
        "root_request_name": root_request_name,
        "generation": generation,
        "parent_task_dir": parent_task_dir,
        "child_generation": child_generation,
        "child_task_dir": child_task_dir,
        "child_task_path": str(child_task_path),
        "recovery_job_count": len(recovery_job_ids),
        "recovery_job_ids": recovery_job_ids,
        "recovery_state_counts": count_states(job_map, recovery_job_id_set),
        "blocking_job_ids": blocking_job_ids,
        "blocking_state_counts": count_states(job_map, set(blocking_job_ids)),
        "skipped_jobs_without_time": skipped_jobs_without_time,
        "task_results_dir": str(task_results_dir),
        "task_not_finished_lumis": str(task_not_finished_lumis),
        "report_dir": str(report_dir),
        "preserved_not_finished_lumis": str(preserved_not_finished_lumis),
        "report_processed_lumis": str(report_processed_lumis),
        "recover_cfg": str(recover_cfg),
        "recover_request_name": recover_request_name,
        "original_lumi_mask": cfg_metadata["lumi_mask"],
        "original_units_per_job": int(cfg_metadata["units_per_job"]),
        "publication_enabled": bool(cfg_metadata["publication_enabled"]),
        "original_output_dataset_tag": cfg_metadata["output_dataset_tag"],
        "kill_required": classification != "killed_recovery_candidate",
        "resolved_lumi_mask": None,
        "resolved_lumi_source": None,
        "resolved_lumi_action": None,
    }


def build_plan(args: argparse.Namespace) -> int:
    summary_file = Path(args.summary_file).resolve()
    summary = load_json(summary_file)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    lineage_path = output_dir / LINEAGE_NAME
    lineage = load_lineage(lineage_path)
    crab_data_dir = Path(summary["cwd"]).resolve()
    snapshot_time = parse_snapshot_time(str(summary["generated_at"]))
    entries: list[dict[str, Any]] = []
    fatal_failures: list[str] = []
    counts = {
        "recovery_candidate": 0,
        "mixed": 0,
        "killed_recovery_candidate": 0,
        "failed_only": 0,
        "no_action": 0,
        "query_error": 0,
    }

    for task in summary.get("tasks", []):
        state = infer_status_collection_state(task)
        task_status_file = str(task.get("task_status_file", ""))
        payload: dict[str, Any] | None = None
        if task_status_file:
            payload_path = task_payload_path(summary_file, task_status_file)
            if payload_path.exists():
                payload = load_json(payload_path)
            elif state != STATUS_COLLECTION_HEADER_ONLY_KILLED:
                raise RuntimeError(
                    f"Missing cached task payload for {task['task_dir']}: {payload_path}"
                )
        elif state != STATUS_COLLECTION_HEADER_ONLY_KILLED:
            raise RuntimeError(
                f"Task {task['task_dir']} is missing task_status_file in summary."
            )

        jobs = payload.get("jobs") if payload is not None else None
        if jobs is not None and not isinstance(jobs, dict):
            jobs = None

        entry = build_task_entry(
            task=task,
            jobs=jobs,
            snapshot_time=snapshot_time,
            crab_data_dir=crab_data_dir,
            output_dir=output_dir,
            stuck_hours=float(args.stuck_hours),
            recovery_suffix=str(args.recovery_suffix),
            lineage=lineage,
        )
        counts[entry["classification"]] += 1
        if entry["classification"] == "query_error":
            fatal_failures.append(entry["task_dir"])
        entries.append(entry)

    update_current_nodes_in_lineage(lineage, entries)
    lineage["generated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(lineage_path, lineage)
    tracked_manifest_path = write_tracked_manifest(lineage, output_dir)

    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary_file": str(summary_file),
        "status_cache_dir": str(summary_file.parent.resolve()),
        "output_dir": str(output_dir),
        "lineage_file": str(lineage_path),
        "tracked_manifest": str(tracked_manifest_path),
        "stuck_hours": float(args.stuck_hours),
        "recovery_suffix": str(args.recovery_suffix),
        "query_failures": fatal_failures,
        "counts": counts,
        "recovery_task_dirs": [
            entry["task_dir"]
            for entry in entries
            if entry["classification"] in {"recovery_candidate", "killed_recovery_candidate"}
        ],
        "mixed_task_dirs": [
            entry["task_dir"] for entry in entries if entry["classification"] == "mixed"
        ],
        "failed_only_task_dirs": [
            entry["task_dir"] for entry in entries if entry["classification"] == "failed_only"
        ],
        "tasks": entries,
    }
    write_json(output_dir / PLAN_NAME, plan)

    if fatal_failures:
        raise RuntimeError(
            "Status snapshot still contains fatal query failures: "
            + ", ".join(fatal_failures)
        )

    print(
        "Prepared recovery plan: "
        f"recovery={counts['recovery_candidate']} "
        f"killed={counts['killed_recovery_candidate']} "
        f"mixed={counts['mixed']} "
        f"failed_only={counts['failed_only']} "
        f"no_action={counts['no_action']}"
    )
    return 0


def load_plan(path: Path) -> dict[str, Any]:
    plan = load_json(path)
    tasks = plan.get("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError(f"Malformed recovery plan {path}: missing tasks list.")
    return plan


def save_plan(path: Path, plan: dict[str, Any]) -> None:
    write_json(path, plan)


def find_task(plan: dict[str, Any], task_dir: str) -> dict[str, Any]:
    for task in plan["tasks"]:
        if task["task_dir"] == task_dir:
            return task
    raise KeyError(f"Task {task_dir} is not present in recovery plan.")


def finished_job_count(task: dict[str, Any]) -> int:
    job_states = task.get("job_states") or {}
    raw_value = job_states.get("finished", 0)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 0


def has_explicit_zero_finished_jobs(task: dict[str, Any]) -> bool:
    job_states = task.get("job_states")
    if not isinstance(job_states, dict) or not job_states:
        return False
    return finished_job_count(task) == 0


def resolve_lumi_for_task(task: dict[str, Any]) -> tuple[str, str, str]:
    preserved_not_finished_lumis = Path(task["preserved_not_finished_lumis"]).resolve()
    task_not_finished_lumis = Path(task["task_not_finished_lumis"]).resolve()
    original_lumi_mask = task.get("original_lumi_mask")

    if json_file_nonempty(preserved_not_finished_lumis):
        return "submit", "preserved_not_finished", str(preserved_not_finished_lumis)

    if preserved_not_finished_lumis.is_file():
        return "skip", "no_not_finished_lumis", ""

    if json_file_nonempty(task_not_finished_lumis):
        return "submit", "task_results_not_finished", str(task_not_finished_lumis)

    if task_not_finished_lumis.is_file():
        return "skip", "no_not_finished_lumis", ""

    if task["classification"] == "killed_recovery_candidate" and original_lumi_mask:
        return "submit", "original_lumi_mask_fallback", str(original_lumi_mask)

    if has_explicit_zero_finished_jobs(task) and original_lumi_mask:
        return "submit", "original_lumi_mask_no_finished_jobs", str(original_lumi_mask)

    return "error", "missing_not_finished_lumis", ""


def render_recovery_config(task: dict[str, Any], template_path: Path) -> Path:
    cfg_path = Path(task["cfg_path"]).resolve()
    metadata = parse_original_cfg_metadata(cfg_path)

    original_units = int(metadata["units_per_job"])
    publication_enabled = bool(metadata["publication_enabled"])
    default_output_dataset_tag = (
        str(metadata["output_dataset_tag"])
        if publication_enabled and metadata["output_dataset_tag"] is not None
        else str(task["recover_request_name"])
    )

    lumi_mask_path = normalize_lumi_mask_value(
        str(task.get("resolved_lumi_mask") or task["preserved_not_finished_lumis"])
    )
    replacements = {
        "__ORIGINAL_CONFIG__": repr(str(cfg_path)),
        "__ORIGINAL_REQUEST_NAME__": repr(str(task["request_name"])),
        "__REQUEST_NAME__": repr(str(task["recover_request_name"])),
        "__LUMI_MASK__": repr(lumi_mask_path),
        "__UNITS_PER_JOB__": str(original_units),
        "__DEFAULT_OUTPUT_DATASET_TAG__": repr(default_output_dataset_tag),
    }

    rendered = template_path.read_text()
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)

    unresolved = sorted(set(re.findall(r"__[A-Z0-9_]+__", rendered)))
    if unresolved:
        raise ValueError(
            "Unresolved placeholders in rendered recovery config for "
            f"{cfg_path}: {unresolved}"
        )

    output_path = Path(task["recover_cfg"]).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered)
    return output_path


def render_one(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan_file).resolve()
    plan = load_plan(plan_path)
    task = find_task(plan, args.task)

    if task["classification"] not in RECOVERY_RENDER_CLASSES:
        raise RuntimeError(
            f"Task {task['task_dir']} is classified as {task['classification']} and does not need a recovery config."
        )

    template_path = Path(__file__).with_name("crab3_recovery_template.py")
    output_path = render_recovery_config(task, template_path)
    print(output_path)
    return 0


def render_all(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan_file).resolve()
    plan = load_plan(plan_path)
    rendered_paths: list[str] = []

    for task in plan["tasks"]:
        if task["classification"] not in RECOVERY_RENDER_CLASSES:
            continue
        template_path = Path(__file__).with_name("crab3_recovery_template.py")
        rendered_paths.append(str(render_recovery_config(task, template_path)))

    manifest_path = Path(plan["output_dir"]) / CONFIG_MANIFEST_NAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("\n".join(rendered_paths) + ("\n" if rendered_paths else ""))
    print(f"Rendered {len(rendered_paths)} recovery config(s)")
    print(manifest_path)
    return 0


def list_executable(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan_file).resolve()
    plan = load_plan(plan_path)
    include_classes = {"recovery_candidate", "killed_recovery_candidate"}
    if args.include_mixed:
        include_classes.add("mixed")

    for task in plan["tasks"]:
        if task["classification"] not in include_classes:
            continue
        print(
            "\t".join(
                [
                    task["task_dir"],
                    task["task_path"],
                    task["report_dir"],
                    task["preserved_not_finished_lumis"],
                    task["recover_cfg"],
                    task["classification"],
                ]
            )
        )
    return 0


def resolve_lumi_mask(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan_file).resolve()
    plan = load_plan(plan_path)
    task = find_task(plan, args.task)

    if task["classification"] not in RECOVERY_RENDER_CLASSES:
        raise RuntimeError(
            f"Task {task['task_dir']} is classified as {task['classification']} and does not need recovery resolution."
        )

    action, source, path = resolve_lumi_for_task(task)
    task["resolved_lumi_action"] = action
    task["resolved_lumi_source"] = source
    task["resolved_lumi_mask"] = path or None
    save_plan(plan_path, plan)
    print("\t".join([action, source, path]))
    return 0


def record_submission(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan_file).resolve()
    plan = load_plan(plan_path)
    task = find_task(plan, args.task)

    if task["classification"] not in RECOVERY_RENDER_CLASSES:
        raise RuntimeError(
            f"Task {task['task_dir']} is classified as {task['classification']} and does not spawn recovery submissions."
        )
    if task.get("resolved_lumi_action") != "submit" or not task.get("resolved_lumi_mask"):
        raise RuntimeError(
            f"Task {task['task_dir']} has no resolved recovery lumi mask; run resolve-lumi-mask first."
        )

    lineage_path = Path(plan["lineage_file"]).resolve()
    lineage = load_lineage(lineage_path)
    child_task_dir = str(task["child_task_dir"])
    child_node = {
        "task_dir": child_task_dir,
        "task_path": str(Path(task["child_task_path"]).resolve()),
        "cfg": str(Path(task["recover_cfg"]).resolve()),
        "cfg_path": str(Path(task["recover_cfg"]).resolve()),
        "request_name": task["recover_request_name"],
        "root_request_name": task["root_request_name"],
        "generation": int(task["child_generation"]),
        "parent_task_dir": task["task_dir"],
        "status_collection_state": STATUS_COLLECTION_NOT_COLLECTED,
        "original_lumi_mask": task.get("original_lumi_mask"),
        "planned_lumi_mask": task["resolved_lumi_mask"],
        "planned_lumi_source": task["resolved_lumi_source"],
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    lineage.setdefault("nodes", {})[child_task_dir] = child_node
    add_lineage_edge(lineage, task["task_dir"], child_task_dir)
    lineage["generated_at"] = datetime.now(timezone.utc).isoformat()
    write_json(lineage_path, lineage)
    tracked_manifest_path = write_tracked_manifest(lineage, Path(plan["output_dir"]).resolve())
    print(child_task_dir)
    print(tracked_manifest_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ensure_cmssw_env()
    if args.command == "plan":
        return build_plan(args)
    if args.command == "render-one":
        return render_one(args)
    if args.command == "render-all":
        return render_all(args)
    if args.command == "resolve-lumi-mask":
        return resolve_lumi_mask(args)
    if args.command == "record-submission":
        return record_submission(args)
    return list_executable(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI error reporting
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
'''
