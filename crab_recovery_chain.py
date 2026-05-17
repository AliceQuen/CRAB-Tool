#!/usr/bin/env python3
"""Shared recovery-chain helpers for the unified CRAB state file."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChainAppendSpec:
    task_dir: str
    cfg_path: str
    task_path: str
    request_name: str
    planned_lumi_mask: Any
    planned_lumi_source: str
    original_lumi_mask: Any | None = None
    original_units_per_job: int | None = None
    publication_enabled: bool = False
    original_output_dataset_tag: str | None = None
    config_metadata: dict[str, Any] | None = None


def _attempts(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict(state.setdefault("attempts", {}))


def _child_map(state: dict[str, Any]) -> dict[str, str]:
    attempts = state.get("attempts", {})
    children: dict[str, str] = {}
    for task_dir, attempt in attempts.items():
        parent = attempt.get("parent_attempt_id")
        if parent in (None, ""):
            continue
        parent = str(parent)
        if parent not in attempts:
            raise RuntimeError(
                f"Attempt {task_dir} points to missing parent {parent}."
            )
        if parent == task_dir:
            raise RuntimeError(f"Attempt {task_dir} points to itself as parent.")
        if parent in children:
            raise RuntimeError(
                f"Branching recovery chain detected at {parent}: "
                f"{children[parent]} and {task_dir}."
            )
        children[parent] = str(task_dir)
    return children


def rebuild_chain_index(state: dict[str, Any]) -> None:
    attempts = state.setdefault("attempts", {})
    children = _child_map(state)
    roots = [
        str(task_dir)
        for task_dir, attempt in attempts.items()
        if attempt.get("parent_attempt_id") in (None, "")
    ]
    families: dict[str, Any] = {}
    visited: set[str] = set()

    for root in sorted(roots):
        ordered: list[str] = []
        current = root
        generation = 0
        local_seen: set[str] = set()
        while current is not None:
            if current in local_seen:
                raise RuntimeError(f"Cycle detected in recovery chain at {current}.")
            local_seen.add(current)
            visited.add(current)
            attempt = attempts[current]
            attempt["task_dir"] = current
            attempt["family_id"] = root
            attempt["generation"] = generation
            ordered.append(current)
            current = children.get(current)
            generation += 1
        families[root] = {
            "root_task_dir": root,
            "root_cfg": attempts[root].get("cfg"),
            "attempt_order": ordered,
            "latest_attempt_id": ordered[-1],
        }

    missing = sorted(set(attempts) - visited)
    if missing:
        raise RuntimeError(
            "Unreachable recovery attempts detected while rebuilding the chain index: "
            + ", ".join(missing)
        )

    state["families"] = families
    state["task_count"] = len(attempts)


def get_root_task(state: dict[str, Any], task_dir: str) -> str:
    attempts = state.get("attempts", {})
    if task_dir not in attempts:
        raise KeyError(f"Task {task_dir} is not present in state file.")
    current = task_dir
    seen: set[str] = set()
    while True:
        parent = attempts[current].get("parent_attempt_id")
        if parent in (None, ""):
            return str(current)
        parent = str(parent)
        if parent not in attempts:
            raise RuntimeError(f"Attempt {current} points to missing parent {parent}.")
        if current in seen:
            raise RuntimeError(f"Cycle detected while walking parents from {task_dir}.")
        seen.add(current)
        current = parent


def get_latest_task(state: dict[str, Any], task_dir: str) -> str:
    root = get_root_task(state, task_dir)
    family = state.get("families", {}).get(root)
    if family is None:
        rebuild_chain_index(state)
        family = state["families"][root]
    return str(family["latest_attempt_id"])


def get_prev_task(state: dict[str, Any], task_dir: str) -> str | None:
    attempts = state.get("attempts", {})
    if task_dir not in attempts:
        raise KeyError(f"Task {task_dir} is not present in state file.")
    parent = attempts[task_dir].get("parent_attempt_id")
    return None if parent in (None, "") else str(parent)


def get_next_task(state: dict[str, Any], task_dir: str) -> str | None:
    attempts = state.get("attempts", {})
    if task_dir not in attempts:
        raise KeyError(f"Task {task_dir} is not present in state file.")
    return _child_map(state).get(task_dir)


def validate_append_structure(state: dict[str, Any], parent_task: str, child_task: str) -> None:
    attempts = state.get("attempts", {})
    if parent_task not in attempts:
        raise KeyError(f"Parent task {parent_task} is not present in state file.")
    if child_task in attempts:
        raise RuntimeError(f"Child task {child_task} is already present in state file.")
    if parent_task == child_task:
        raise RuntimeError("Parent and child task ids must be different.")
    if get_latest_task(state, parent_task) != parent_task:
        raise RuntimeError(
            f"Task {parent_task} is not the latest attempt in its family."
        )
    if get_next_task(state, parent_task) is not None:
        raise RuntimeError(f"Task {parent_task} already has a child attempt.")


def append_after(
    state: dict[str, Any],
    parent_task: str,
    child: ChainAppendSpec,
    *,
    status_collection_state: str,
) -> None:
    validate_append_structure(state, parent_task, child.task_dir)
    parent_attempt = state["attempts"][parent_task]
    state["attempts"][child.task_dir] = {
        "task_dir": child.task_dir,
        "cfg": child.cfg_path,
        "cfg_path": child.cfg_path,
        "task_path": child.task_path,
        "request_name": child.request_name,
        "family_id": parent_attempt.get("family_id") or get_root_task(state, parent_task),
        "parent_attempt_id": parent_task,
        "generation": int(parent_attempt.get("generation", 0)) + 1,
        "planned_lumi_mask": child.planned_lumi_mask,
        "planned_lumi_source": child.planned_lumi_source,
        "original_lumi_mask": child.original_lumi_mask,
        "original_units_per_job": child.original_units_per_job,
        "publication_enabled": child.publication_enabled,
        "original_output_dataset_tag": child.original_output_dataset_tag,
        "config_metadata": child.config_metadata,
        "status_revision": None,
        "status": {"status_collection_state": status_collection_state},
        "recovery": {},
        "artifacts": {},
    }
    rebuild_chain_index(state)
