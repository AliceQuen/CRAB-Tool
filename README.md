# CRAB data submission helper

This directory contains a self-contained CRAB workflow for submitting
`MultiLepPAT` data jobs from 2022 through 2025.

## Preconditions

Every helper script in this directory expects:

```bash
cmsenv
export X509_USER_PROXY="$(voms-proxy-info -path)"
```

Use `--help` on any wrapper or Python CLI to see the full command reference.
Shell-wrapper help is available before `cmsenv`, but the Python recovery
builder now imports `FWCore.PythonUtilities.LumiList` directly and therefore
should be invoked under `cmsenv`.

The recovery-state Python tests follow the same rule. Run the local suite from
an active CMSSW runtime:

```bash
python3 -m unittest discover -s src/HeavyFlavorAnalysis/TPS-Onia2MuMu/test/crabData -p 'test_crab*.py'
```

## What drives the configuration

- `crab3_template.py` is the base CRAB template.
- `crab3_recovery_template.py` is the user-editable recovery overlay template.
- `generate_crab_configs.py` expands the template using local `RundataList_*.txt`
  files.
- `registerData.sh` is a thin wrapper around `generate_crab_configs.py`.
- `../ConfFile_cfg.py` is the CMSSW config used by all generated CRAB jobs.
  Era-specific global-tag selection stays in `ConfFile_cfg.py`.
- `RundataList_*.txt` are the local dataset lists for 2022, 2023, 2024, and 2025.

The generated CRAB configs inject:

- `runOnMC=False`
- `era=<parsed from dataset path>`
- `outputFile=<campaign-specific ROOT filename>`
- `analysisMode=JpsiJpsiPhi`

## Quick start

Generate CRAB configs and refresh the manifest:

```bash
./registerData.sh
```

Print the submission commands without executing them:

```bash
./submit.sh
```

Submit for real:

```bash
./submit.sh --execute
```

Collect cached CRAB status snapshots:

```bash
./status.sh
```

Inspect raw CRAB status output instead of the cached JSON flow:

```bash
./status.sh --raw-status -- --verboseErrors
```

Resubmit only failed jobs:

```bash
./resubmit.sh --execute
```

Prepare recovery plans and render recovery configs:

```bash
./prepare_recovery_tasks.sh
```

Print the recovery report/preserve/kill/render/submit sequence without executing it:

```bash
./kill_unfinished_and_submit_recover.sh
```

Run the recovery sequence for real:

```bash
./kill_unfinished_and_submit_recover.sh --execute
```

Include mixed tasks in the recovery execution set:

```bash
./kill_unfinished_and_submit_recover.sh --execute --allow-mixed-tasks
```

Kill every generated task in the manifest:

```bash
./kill.sh --execute
```

## CLI reference

### `registerData.sh`

Generate CRAB configs from the local dataset lists.

```bash
./registerData.sh [generator options]
```

Notes:

- Forwards all non-help arguments to `generate_crab_configs.py`.
- Use `./generate_crab_configs.py --help` for the full generator option list.

### `submit.sh`

Submit every config listed in the manifest.

```bash
./submit.sh [options] [-- crab submit options]
```

Key options:

- `--dry-run`
- `--execute`
- `--manifest PATH`

### `status.sh`

Collect cached machine-readable status snapshots, or call `crab status`
directly. Cache-updating refreshes now skip tasks already cached as terminal
(`server=KILLED`, or `scheduler=COMPLETED` with all jobs finished) unless you
force a live refresh.

```bash
./status.sh [options] [-- crab status options]
```

Key options:

- `--cached-status`
- `--raw-status`
- `--refresh-terminal-statuses`
- `--manifest PATH`
- `--cache-dir PATH`

Outputs:

- `status_cache/latest_state.json`

### `resubmit.sh`

Refresh or reuse cached task status, then resubmit only failed CRAB jobs.

```bash
./resubmit.sh [options] [-- crab resubmit options]
```

Key options:

- `--dry-run`
- `--execute`
- `--use-cached-status`
- `--refresh-status`
- `--refresh-terminal-statuses`
- `--status-cache-dir PATH`

### `prepare_recovery_tasks.sh`

Refresh derived recovery metadata in the unified state file and render recovery
configs for stuck unfinished jobs.

```bash
./prepare_recovery_tasks.sh [options]
```

Key options:

- `--use-cached-status`
- `--refresh-status`
- `--refresh-terminal-statuses`
- `--status-cache-dir PATH`
- `--recovery-cache-dir PATH`
- `--stuck-hours HOURS`
- `--include-repeated-failures`
- `--failed-retry-threshold N`

Outputs:

- `status_cache/latest_state.json`
- `recovery_cache/generated_recovery_configs.txt`
- `recovery_cache/configs/*.py`
- `recovery_cache/lumimasks/*.json`

Recovery overrides:

- Edit `crab3_recovery_template.py` when you need recovery-specific overrides
  such as `Data.unitsPerJob`, `Data.splitting`, `Data.publication`,
  `JobType.pyCfgParams`, `JobType.numCores`, `JobType.maxMemoryMB`, or other
  direct `config.<Section>.<field>` assignments.
- The recovery template now uses normal CRAB config syntax, not `RECOVERY_*`
  overlay variables. Edit the direct `config.*` assignments in the template or
  add new literal `config.*` assignments as needed.
- Re-run `./prepare_recovery_tasks.sh` or
  `./crab_recovery_task_builder.py render-all ...` after editing the template so
  the generated recovery configs under `recovery_cache/configs/` pick up the
  new direct config values.
- `prepare_recovery_tasks.sh` now calls `render-all --skip-unresolved-lumi`, so
  normal unfinished tasks that still need a later `crab report` are kept in the
  executable recovery set without aborting the plan refresh.
- The builder preserves literal `config.<Section>.<field>` assignments from the
  original task config and applies the literal assignments from
  `crab3_recovery_template.py` on top, so fields not restated in the recovery
  template remain inherited automatically.
- `JobType.pyCfgParams` in the recovery template is a direct list assignment.
  Multiline literal lists are supported; computed Python logic is not.
- During actual recovery execution, normal tasks preserve
  `results/notFinishedLumis.json` into `recovery_cache/reports/<task>/` before
  the original task is killed. The rendered recovery config then uses that
  preserved coverage written back out as a generated lumi-mask JSON file.
- Because of that ordering, `recovery_cache/generated_recovery_configs.txt` can
  be a partial manifest after plan preparation. Tasks whose missing lumi
  coverage is not yet locally known are rendered later by the execution wrapper
  after `resolve-lumi-mask` succeeds.
- The execution wrapper re-checks the live CRAB server status before deciding
  whether a task should follow the normal `report -> kill` path or the
  already-killed fallback path, even when `--use-cached-status` and
  `--use-prepared-plan` are enabled.
- Existing recovery tasks created outside the current workflow can be
  registered manually with:

```bash
./crab_recovery_task_builder.py add-to-chain \
  --state-file status_cache/latest_state.json \
  --parent-task crab_parent \
  --child-task-dir crab_parent__recover1 \
  --child-cfg /abs/path/to/crab_parent__recover1.py
```

- Manual chaining succeeds only when the child config's `config.Data.lumiMask`
  exactly matches the parent attempt's missing lumi coverage.

### `kill_unfinished_and_submit_recover.sh`

Execute the recovery flow selected by the recovery metadata stored in
`status_cache/latest_state.json`.

```bash
./kill_unfinished_and_submit_recover.sh [options]
```

Key options:

- `--dry-run`
- `--execute`
- `--use-prepared-plan`
- `--rebuild-plan`
- `--use-cached-status`
- `--refresh-status`
- `--refresh-terminal-statuses`
- `--allow-mixed-tasks`
- `--skip-mixed-tasks`
- `--include-repeated-failures`
- `--failed-retry-threshold N`

### `kill.sh`

Kill every task listed in the manifest.

```bash
./kill.sh [options] [-- crab kill options]
```

Key options:

- `--dry-run`
- `--execute`
- `--manifest PATH`

## Python CLI reference

### `generate_crab_configs.py`

Generate CRAB config files from the local dataset lists.

```bash
./generate_crab_configs.py --help
```

### `crab_status_snapshot.py`

Collect cached CRAB status into the authoritative state file or list failed
jobs from that state file.

```bash
./crab_status_snapshot.py --help
./crab_status_snapshot.py collect --help
./crab_status_snapshot.py list-failed --help
```

`list-failed` prints one tab-separated line per task:

```text
task_dir<TAB>comma-separated job ids<TAB>failed job count
```

### `crab_recovery_task_builder.py`

Refresh recovery metadata in the state file, resolve lumi-mask fallbacks,
render recovery configs, or list executable recovery tasks.

```bash
./crab_recovery_task_builder.py --help
./crab_recovery_task_builder.py refresh-recovery --help
./crab_recovery_task_builder.py render-all --help
./crab_recovery_task_builder.py resolve-lumi-mask --help
./crab_recovery_task_builder.py add-to-chain --help
```

`list-executable` prints:

```text
task_dir<TAB>task_path<TAB>report_dir<TAB>preserved_not_finished_lumis<TAB>recover_cfg<TAB>classification
```

`render-all --skip-unresolved-lumi` keeps the same state-file-driven task
selection, but skips executable tasks whose normal recovery path still needs a
later `crab report` before a concrete recovery lumi mask exists.

## Recovery classification

`prepare_recovery_tasks.sh` reads and updates `status_cache/latest_state.json`
and classifies the latest attempt in each recovery family into:

- `recovery_candidate`: tasks whose `unsubmitted` jobs or sufficiently old
  `idle` / `cooloff` jobs should move to a recovery task immediately.
- `killed_recovery_candidate`: tasks whose `crab status --json` output contains
  only the CRAB header, with `Status on the CRAB server: KILLED`, so the task
  should still move into the recovery flow even without per-job JSON.
- `mixed`: tasks that have recovery-candidate jobs but also still contain other
  non-finished jobs such as `running`, `transferring`, `failed`, or fresher
  `idle` / `cooloff` jobs.
- `repeated_failure_recovery_candidate`: tasks selected only when
  `--include-repeated-failures` is set, where failed jobs have reached the
  configured CRAB `Retries` threshold and should move to the task-level
  kill-and-recovery flow instead of another `crab resubmit`.
- `failed_only`: tasks that only need the existing `./resubmit.sh` flow.

Mixed tasks are excluded from recovery execution by default. Add
`--allow-mixed-tasks` when you want to include them.

Repeated failed jobs are excluded from recovery by default. Add
`--include-repeated-failures` to `prepare_recovery_tasks.sh` or
`kill_unfinished_and_submit_recover.sh --rebuild-plan` to promote failed jobs
whose CRAB status JSON reports `Retries >= --failed-retry-threshold`; the
default threshold is `1`.

## Environment variable compatibility

The preferred interface is the command line. The wrappers still accept the old
environment variables as fallbacks:

- `CRAB_MANIFEST`
- `STATUS_CACHE_DIR`
- `RECOVERY_CACHE_DIR`
- `DRY_RUN`
- `RAW_STATUS`
- `USE_CACHED_STATUS`
- `USE_PREPARED_PLAN`
- `ALLOW_MIXED_TASKS`
- `STUCK_HOURS`
- `INCLUDE_REPEATED_FAILURES`
- `FAILED_RETRY_THRESHOLD`

Precedence is:

1. command-line flag
2. environment variable
3. built-in default

Examples:

```bash
# Preferred
./submit.sh --execute

# Still supported
DRY_RUN=0 ./submit.sh
```

## Cache model

- `status_cache/latest_state.json` is the only authoritative cache file.
- Each original task forms one recovery family.
- Recovery ancestry is a strict linear chain, not a DAG.
- Every attempt stores its own `planned_lumi_mask` as canonical compact lumi
  coverage derived through `FWCore.PythonUtilities.LumiList`.
- Recovery-of-recovery falls back to the parent attempt's planned compact
  coverage rather than widening back to the root task's full lumi mask.
- `recovery_cache/` stores generated artifacts only: rendered configs and
  preserved report files. It is no longer an independent state store.
- Builder-generated recovery configs receive a generated lumi-mask JSON file
  under `recovery_cache/lumimasks/`; manually chained tasks keep their original
  lumi-mask file unchanged.

## Notes

- The dataset lists are copied locally into this directory so `crabData` remains
  self-contained.
- The generator removes previously generated CRAB configs listed in
  `generated_crab_configs.txt` before writing a fresh set.
- Generated request names encode the stream index and the processed campaign so
  distinct prompt-reco versions do not collide.
- `crab status --json` still prints a human-readable header before the JSON
  payload, so `crab_status_snapshot.py` extracts the final JSON object from
  stdout before summarizing job states.
- A killed task may return only the CRAB header with `Status on the CRAB
  server: KILLED` and no JSON payload. The cached status flow now records that
  as a non-fatal `header_only_killed` state instead of aborting recovery.
  planning.
- Normal recovery tasks now follow the CRAB flow of `crab report` on the
  original task, preserving `results/notFinishedLumis.json` into
  `recovery_cache/reports/<task>/`, then `crab kill`, and finally `crab submit`
  of a new config that reuses the original task settings with a new request
  name and the preserved not-finished lumi coverage.
- `./kill_unfinished_and_submit_recover.sh --rebuild-plan --dry-run` now works
  for that normal recovery path as well. Plan rebuilding refreshes recovery
  metadata and prints the later `report -> kill -> resolve-lumi-mask ->
  render-one -> submit` sequence without requiring `prepare_recovery_tasks.sh`
  to pre-render every executable task up front.
- The generated recovery config is now rendered through
  `crab3_recovery_template.py`, which now uses the same direct WMCore-style
  CRAB syntax as the original template. The builder parses literal
  `config.<Section>.<field>` assignments from both the original config and the
  recovery template, preserves inherited original fields, and emits a merged
  recovery config without executing either file.
- Recovery lumi comparison and manual chain validation use the CMSSW
  `FWCore.PythonUtilities.LumiList` implementation rather than raw path
  equality. Equivalent lumi masks written in different compact forms therefore
  compare correctly.
- `lumisToProcess.json` is informational and is not used as the recovery lumi
  mask. The normal recovery source is `notFinishedLumis.json`.
- If a task has explicitly zero finished jobs and `crab report` therefore
  cannot produce `notFinishedLumis.json`, the recovery flow falls back to the
  original task lumi mask and resubmits the full original lumi scope.
- If an already-killed task has no preserved or existing
  `results/notFinishedLumis.json`, the recovery flow falls back to the original
  task lumi mask and resubmits the full lumi set.
- Recovery lineage is stored inside `status_cache/latest_state.json` as one
  family per root task plus a linear ordered attempt chain. Generated recovery
  request names use numbered descendants such as `...__recover1`,
  `...__recover2`, and later recoveries inherit the parent attempt's planned
  lumi mask instead of widening back to the root task scope.
- Manual registration through `add-to-chain` uses the same append path as
  automatic `record-submission`, so once a legacy child is registered it will
  be queried automatically by later `./status.sh` runs.
