#!/usr/bin/env python3
"""Resubmit failed CRAB jobs using the authoritative cached status view."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

import crab_status_snapshot as snapshot


class HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter
):
    """Help formatter with defaults and preserved line breaks."""


def parse_args(argv: list[str] | None = None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh the cached latest-attempt status view if needed, then resubmit "
            "only the failed CRAB jobs recorded in latest_state.json."
        ),
        formatter_class=HelpFormatter,
    )
    parser.add_argument(
        "--manifest",
        default="generated_crab_configs.txt",
        help="Manifest that lists one CRAB config path per line.",
    )
    parser.add_argument(
        "--status-cache-dir",
        default="status_cache",
        help="Directory that stores latest_state.json.",
    )
    parser.add_argument(
        "--state-file",
        default=None,
        help="Explicit path to latest_state.json.",
    )
    execution_group = parser.add_mutually_exclusive_group()
    execution_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Print crab resubmit commands without executing them.",
    )
    execution_group.add_argument(
        "--execute",
        action="store_true",
        help="Execute crab resubmit for each failed task.",
    )
    refresh_group = parser.add_mutually_exclusive_group()
    refresh_group.add_argument(
        "--use-cached-status",
        action="store_true",
        help="Reuse the existing latest_state.json if it exists.",
    )
    refresh_group.add_argument(
        "--refresh-status",
        action="store_true",
        help="Refresh latest_state.json before resubmitting.",
    )
    parser.add_argument(
        "--refresh-terminal-statuses",
        action="store_true",
        help="Force live refresh even for cached terminal tasks.",
    )
    return parser.parse_known_args(argv)


def resolve_state_file(args: argparse.Namespace) -> Path:
    if args.state_file:
        return Path(args.state_file)
    return Path(args.status_cache_dir) / snapshot.STATE_NAME


def is_no_jobs_to_resubmit_output(output: str) -> bool:
    normalized = output.lower()
    return (
        "no jobs to resubmit" in normalized
        or "nothing to resubmit" in normalized
        or "don't have jobs to resubmit" in normalized
        or "doesn't have jobs to resubmit" in normalized
    )


def refresh_latest_status(args: argparse.Namespace) -> int:
    status_args = argparse.Namespace(
        manifest=args.manifest,
        cache_dir=args.status_cache_dir,
        state_file=str(resolve_state_file(args)),
        no_update_cache=False,
        raw_output=False,
        refresh_terminal_statuses=bool(args.refresh_terminal_statuses),
    )
    return snapshot.run_query_latest(status_args, [])


def run_resubmit(args: argparse.Namespace, extra_args: list[str]) -> int:
    snapshot.ensure_cmssw_env()
    snapshot.ensure_proxy_env()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing {manifest_path}. Run ./registerData.sh first.")

    state_path = resolve_state_file(args).resolve()
    use_cached_status = args.use_cached_status and not args.refresh_status
    dry_run = not args.execute

    if not use_cached_status or not state_path.exists():
        refresh_exit = refresh_latest_status(args)
        if refresh_exit != 0:
            return refresh_exit

    state = snapshot.ensure_state_shape(snapshot.load_json(state_path))
    query_failures = snapshot.latest_query_failures(state)
    if query_failures:
        print(
            "Status snapshot contains query failures; refresh status before resubmitting: "
            + ", ".join(query_failures),
            file=sys.stderr,
        )
        return 1

    failed_entries = snapshot.iter_latest_failed_entries(state)
    if not failed_entries:
        print("No failed jobs found in status snapshot.")
        return 0

    failed_tasks: list[str] = []
    for task_dir, failed_job_ids, failed_count in failed_entries:
        cmd = ["crab", "resubmit", "-d", task_dir, "--jobids", ",".join(failed_job_ids)]
        if extra_args:
            cmd.extend(extra_args)

        if dry_run:
            print(f"[failed={failed_count}] " + " ".join(shlex.quote(part) for part in cmd))
            continue

        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = completed.stdout + completed.stderr
        if completed.returncode == 0:
            if output:
                print(output, end="" if output.endswith("\n") else "\n")
            continue
        if is_no_jobs_to_resubmit_output(output):
            if output:
                print(output, end="" if output.endswith("\n") else "\n")
            print(f"Skipping {task_dir}: no jobs to resubmit.")
            continue

        if output:
            print(output, end="" if output.endswith("\n") else "\n", file=sys.stderr)
        print(f"Resubmit failed for {task_dir}.", file=sys.stderr)
        failed_tasks.append(task_dir)

    if failed_tasks:
        print(f"Resubmit failures in {len(failed_tasks)} task(s):", file=sys.stderr)
        for task_dir in failed_tasks:
            print(f"  {task_dir}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args, extra_args = parse_args(argv)
    return run_resubmit(args, extra_args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI error reporting
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
