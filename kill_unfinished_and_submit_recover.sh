#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
source "${SCRIPT_DIR}/crab_common.sh"

MANIFEST="${CRAB_MANIFEST:-generated_crab_configs.txt}"
CLI_DRY_RUN=""
CLI_USE_CACHED_STATUS=""
CLI_USE_PREPARED_PLAN=""
CLI_ALLOW_MIXED_TASKS=""
CLI_REFRESH_TERMINAL_STATUSES=""
CLI_INCLUDE_REPEATED_FAILURES=""
STATUS_CACHE_DIR="${STATUS_CACHE_DIR:-status_cache}"
RECOVERY_CACHE_DIR="${RECOVERY_CACHE_DIR:-recovery_cache}"
FAILED_RETRY_THRESHOLD="${FAILED_RETRY_THRESHOLD:-1}"
STATE_FILE="${STATUS_CACHE_DIR}/latest_state.json"
SHOW_HELP=0

show_help() {
    cat <<'EOF'
Usage: ./kill_unfinished_and_submit_recover.sh [options]

For normal recovery tasks, run crab report first, preserve
notFinishedLumis.json into recovery_cache/, kill the original task, resolve the
recovery lumi mask, render the corresponding recovery config, and submit the
recovery task. Already-killed tasks skip the new kill step and fall back to the
preserved or original-task lumi information.

Options:
  -h, --help                Show this help text and exit.
  --manifest PATH           Manifest file to read. Falls back to CRAB_MANIFEST.
  --status-cache-dir PATH   Status cache directory. Falls back to STATUS_CACHE_DIR.
  --recovery-cache-dir PATH Recovery cache directory. Falls back to RECOVERY_CACHE_DIR.
  --dry-run                 Print the kill/report/render/submit sequence only.
  --execute                 Execute the kill/report/render/submit sequence.
  --use-cached-status       Reuse the existing status snapshot if possible.
  --refresh-status          Force a fresh status collection before rebuilding the plan.
  --refresh-terminal-statuses
                            Force live refresh even for cached terminal tasks.
  --use-prepared-plan       Reuse the existing recovery metadata in latest_state.json if it exists.
  --rebuild-plan            Refresh recovery metadata before executing.
  --allow-mixed-tasks       Include mixed tasks in the execution set.
  --skip-mixed-tasks        Exclude mixed tasks even if ALLOW_MIXED_TASKS is set.
  --include-repeated-failures
                            Promote failed jobs that already reached the retry threshold.
  --skip-repeated-failures  Disable repeated-failure recovery even if env enables it.
  --failed-retry-threshold N
                            Minimum CRAB retry count for repeated-failure recovery.

Environment fallback:
  CRAB_MANIFEST             Default manifest path.
  STATUS_CACHE_DIR          Default status cache directory.
  RECOVERY_CACHE_DIR        Default recovery cache directory.
  DRY_RUN                   Default dry-run mode (accepted values: 0/1/true/false).
  USE_CACHED_STATUS         Default cache reuse mode (accepted values: 0/1/true/false).
  USE_PREPARED_PLAN         Default plan reuse mode (accepted values: 0/1/true/false).
  ALLOW_MIXED_TASKS         Default mixed-task mode (accepted values: 0/1/true/false).
  INCLUDE_REPEATED_FAILURES Default repeated-failure recovery mode.
  FAILED_RETRY_THRESHOLD    Default failed-job retry threshold.

Preconditions:
  - Run 'cmsenv' in this CMSSW work area first.
  - Export X509_USER_PROXY before mutating CRAB tasks.

Examples:
  ./kill_unfinished_and_submit_recover.sh
  ./kill_unfinished_and_submit_recover.sh --execute
  ./kill_unfinished_and_submit_recover.sh --execute --allow-mixed-tasks
  ./kill_unfinished_and_submit_recover.sh --execute --rebuild-plan --include-repeated-failures

Notes:
  - Killed tasks without a JSON status payload are still eligible for recovery.
  - Normal recovery uses notFinishedLumis.json preserved from crab report
    before the original task is killed.
  - If crab report cannot produce notFinishedLumis.json because zero jobs have
    finished, the original lumi mask is reused for the recovery submission.
  - If a killed task has no preserved or existing notFinishedLumis.json, the
    original lumi mask is reused for the recovery submission.
EOF
}

validate_json_file() {
    local path="$1"
    python3 -c 'import json, pathlib, sys; data = json.loads(pathlib.Path(sys.argv[1]).read_text()); pathlib.Path(sys.argv[1]); print(bool(data))' "$path" >/dev/null
}

preserve_not_finished_lumis() {
    local task_path="$1"
    local report_dir="$2"
    local src="${task_path}/results/notFinishedLumis.json"
    local dst="${report_dir}/notFinishedLumis.json"

    [[ -f "${src}" ]] || return 1
    mkdir -p "${report_dir}"
    cp -f "${src}" "${dst}"
    validate_json_file "${dst}"
}

maybe_preserve_existing_not_finished_lumis() {
    local task_path="$1"
    local report_dir="$2"
    local src="${task_path}/results/notFinishedLumis.json"
    local dst="${report_dir}/notFinishedLumis.json"

    if [[ -f "${src}" ]]; then
        mkdir -p "${report_dir}"
        cp -f "${src}" "${dst}"
        validate_json_file "${dst}"
    fi
}

get_runtime_server_status() {
    local task_path="$1"
    local status_output=""
    local server_status=""

    if ! status_output="$(crab status -d "${task_path}" 2>&1)"; then
        printf '%s\n' "${status_output}" >&2
        return 1
    fi

    server_status="$(
        printf '%s\n' "${status_output}" |
            sed -n 's/^Status on the CRAB server:[[:space:]]*//p' |
            sed -n '1p'
    )"

    if [[ -z "${server_status}" ]]; then
        printf 'Could not determine CRAB server status for %s.\n' "${task_path}" >&2
        printf '%s\n' "${status_output}" >&2
        return 1
    fi

    printf '%s\n' "${server_status}"
}

while (($#)); do
    case "$1" in
        -h|--help)
            SHOW_HELP=1
            shift
            ;;
        --manifest)
            require_option_value "$1" "${2:-}"
            MANIFEST="$2"
            shift 2
            ;;
        --status-cache-dir)
            require_option_value "$1" "${2:-}"
            STATUS_CACHE_DIR="$2"
            shift 2
            ;;
        --recovery-cache-dir)
            require_option_value "$1" "${2:-}"
            RECOVERY_CACHE_DIR="$2"
            shift 2
            ;;
        --dry-run)
            CLI_DRY_RUN=1
            shift
            ;;
        --execute)
            CLI_DRY_RUN=0
            shift
            ;;
        --use-cached-status)
            CLI_USE_CACHED_STATUS=1
            shift
            ;;
        --refresh-status)
            CLI_USE_CACHED_STATUS=0
            shift
            ;;
        --refresh-terminal-statuses)
            CLI_REFRESH_TERMINAL_STATUSES=1
            shift
            ;;
        --use-prepared-plan)
            CLI_USE_PREPARED_PLAN=1
            shift
            ;;
        --rebuild-plan)
            CLI_USE_PREPARED_PLAN=0
            shift
            ;;
        --allow-mixed-tasks)
            CLI_ALLOW_MIXED_TASKS=1
            shift
            ;;
        --skip-mixed-tasks)
            CLI_ALLOW_MIXED_TASKS=0
            shift
            ;;
        --include-repeated-failures)
            CLI_INCLUDE_REPEATED_FAILURES=1
            shift
            ;;
        --skip-repeated-failures)
            CLI_INCLUDE_REPEATED_FAILURES=0
            shift
            ;;
        --failed-retry-threshold)
            require_option_value "$1" "${2:-}"
            FAILED_RETRY_THRESHOLD="$2"
            shift 2
            ;;
        *)
            die "Unknown option for ./kill_unfinished_and_submit_recover.sh: $1"
            ;;
    esac
done

if [[ "${SHOW_HELP}" == "1" ]]; then
    show_help
    exit 0
fi

DRY_RUN="$(resolve_bool "DRY_RUN" "${CLI_DRY_RUN}" "${DRY_RUN:-}" "1")"
USE_CACHED_STATUS="$(resolve_bool "USE_CACHED_STATUS" "${CLI_USE_CACHED_STATUS}" "${USE_CACHED_STATUS:-}" "0")"
USE_PREPARED_PLAN="$(resolve_bool "USE_PREPARED_PLAN" "${CLI_USE_PREPARED_PLAN}" "${USE_PREPARED_PLAN:-}" "0")"
ALLOW_MIXED_TASKS="$(resolve_bool "ALLOW_MIXED_TASKS" "${CLI_ALLOW_MIXED_TASKS}" "${ALLOW_MIXED_TASKS:-}" "0")"
INCLUDE_REPEATED_FAILURES="$(resolve_bool "INCLUDE_REPEATED_FAILURES" "${CLI_INCLUDE_REPEATED_FAILURES}" "${INCLUDE_REPEATED_FAILURES:-}" "0")"
STATE_FILE="${STATUS_CACHE_DIR}/latest_state.json"

require_cmssw_env
require_manifest "${MANIFEST}"
require_proxy_env

if [[ "${USE_PREPARED_PLAN}" != "1" || ! -f "${STATE_FILE}" ]]; then
    prepare_args=(
        --manifest "${MANIFEST}"
        --status-cache-dir "${STATUS_CACHE_DIR}"
        --recovery-cache-dir "${RECOVERY_CACHE_DIR}"
    )
    if [[ "${USE_CACHED_STATUS}" == "1" ]]; then
        prepare_args+=(--use-cached-status)
    else
        prepare_args+=(--refresh-status)
    fi
    if [[ -n "${CLI_REFRESH_TERMINAL_STATUSES}" ]]; then
        prepare_args+=(--refresh-terminal-statuses)
    fi
    prepare_args+=(--failed-retry-threshold "${FAILED_RETRY_THRESHOLD}")
    if [[ "${INCLUDE_REPEATED_FAILURES}" == "1" ]]; then
        prepare_args+=(--include-repeated-failures)
    fi
    ./prepare_recovery_tasks.sh "${prepare_args[@]}"
fi

declare -a builder_args=(
    crab_recovery_task_builder.py
    list-executable
    --state-file "${STATE_FILE}"
)

if [[ "${ALLOW_MIXED_TASKS}" == "1" ]]; then
    builder_args+=(--include-mixed)
fi

if ! task_output="$(python3 "${builder_args[@]}")"; then
    exit 1
fi

if [[ -z "${task_output}" ]]; then
    echo "No recovery tasks selected by ${STATE_FILE}."
    exit 0
fi

while IFS=$'\t' read -r task_dir task_path report_dir preserved_not_finished_lumis recover_cfg classification; do
    [[ -n "${task_dir}" ]] || continue

    cmd_status=(crab status -d "${task_path}")
    cmd_kill=(crab kill -d "${task_path}")
    cmd_report=(crab report -d "${task_path}")
    cmd_resolve=(python3 crab_recovery_task_builder.py resolve-lumi-mask --state-file "${STATE_FILE}" --task "${task_dir}")
    cmd_render=(python3 crab_recovery_task_builder.py render-one --state-file "${STATE_FILE}" --task "${task_dir}")
    cmd_submit=(crab submit -c "${recover_cfg}")
    cmd_record=(python3 crab_recovery_task_builder.py record-submission --state-file "${STATE_FILE}" --task "${task_dir}")
    task_results_not_finished="${task_path}/results/notFinishedLumis.json"

    if [[ "${DRY_RUN}" == "1" ]]; then
        printf '[%s] ' "${classification}"
        printf '%q ' "${cmd_report[@]}"
        printf '\n'
        printf '[%s] cp -f %q %q\n' \
            "${classification}" "${task_results_not_finished}" "${preserved_not_finished_lumis}"
        if [[ "${classification}" == "killed_recovery_candidate" ]]; then
            printf '[%s] preserve-if-present %q -> %q\n' \
                "${classification}" "${task_results_not_finished}" "${preserved_not_finished_lumis}"
        else
            printf '[%s] ' "${classification}"
            printf '%q ' "${cmd_kill[@]}"
            printf '\n'
        fi
        printf '[%s] ' "${classification}"
        printf '%q ' "${cmd_resolve[@]}"
        printf '\n'
        printf '[%s] ' "${classification}"
        printf '%q ' "${cmd_render[@]}"
        printf '\n'
        printf '[%s] ' "${classification}"
        printf '%q ' "${cmd_submit[@]}"
        printf '\n'
        printf '[%s] ' "${classification}"
        printf '%q ' "${cmd_record[@]}"
        printf '\n'
        continue
    fi

    runtime_server_status="$(get_runtime_server_status "${task_path}")" || {
        echo "Failed to fetch runtime CRAB status for ${task_dir}." >&2
        exit 1
    }
    cmd_resolve+=(--runtime-server-status "${runtime_server_status}")

    if ! "${cmd_report[@]}"; then
        echo "crab report failed for ${task_dir}; falling back to any existing notFinishedLumis.json." >&2
    fi

    if ! preserve_not_finished_lumis "${task_path}" "${report_dir}"; then
        maybe_preserve_existing_not_finished_lumis "${task_path}" "${report_dir}"
        echo "No fresh notFinishedLumis.json produced for ${task_dir}; continuing to recovery lumi resolution." >&2
    fi

    if [[ "${runtime_server_status}" != "KILLED" ]]; then
        "${cmd_kill[@]}"
    fi

    if ! resolved_output="$("${cmd_resolve[@]}")"; then
        echo "Failed to resolve recovery lumi mask for ${task_dir}." >&2
        exit 1
    fi
    IFS=$'\t' read -r resolve_action resolve_source resolved_lumi_mask <<< "${resolved_output}"

    if [[ "${resolve_action}" == "skip" ]]; then
        echo "Skipping ${task_dir}: ${resolve_source}."
        continue
    fi
    if [[ "${resolve_action}" != "submit" || -z "${resolved_lumi_mask}" ]]; then
        echo "Could not resolve a recovery lumi mask for ${task_dir}: ${resolve_source}." >&2
        exit 1
    fi

    "${cmd_render[@]}" >/dev/null
    "${cmd_submit[@]}"
    "${cmd_record[@]}" >/dev/null
done < <(printf '%s\n' "${task_output}")
