#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
source "${SCRIPT_DIR}/crab_common.sh"

MANIFEST="${CRAB_MANIFEST:-generated_crab_configs.txt}"
CLI_USE_CACHED_STATUS=""
CLI_REFRESH_TERMINAL_STATUSES=""
CLI_INCLUDE_REPEATED_FAILURES=""
STATUS_CACHE_DIR="${STATUS_CACHE_DIR:-status_cache}"
RECOVERY_CACHE_DIR="${RECOVERY_CACHE_DIR:-recovery_cache}"
STATE_FILE="${STATUS_CACHE_DIR}/latest_state.json"
STUCK_HOURS="${STUCK_HOURS:-48}"
FAILED_RETRY_THRESHOLD="${FAILED_RETRY_THRESHOLD:-1}"
SHOW_HELP=0

show_help() {
    cat <<'EOF'
Usage: ./prepare_recovery_tasks.sh [options]

Refresh or reuse the cached CRAB task status, refresh derived recovery metadata
in the unified state file, and render the recovery configs under recovery_cache/.

Options:
  -h, --help              Show this help text and exit.
  --manifest PATH         Manifest file to read. Falls back to CRAB_MANIFEST.
  --status-cache-dir PATH Status cache directory. Falls back to STATUS_CACHE_DIR.
  --recovery-cache-dir PATH
                          Recovery cache directory. Falls back to RECOVERY_CACHE_DIR.
  --stuck-hours HOURS     Minimum idle/cooloff age required for recovery planning.
  --include-repeated-failures
                          Promote failed jobs that already reached the retry threshold.
  --failed-retry-threshold N
                          Minimum CRAB retry count for repeated-failure recovery.
  --use-cached-status     Reuse the existing status snapshot if it exists.
  --refresh-status        Force a fresh status collection before planning recovery.
  --refresh-terminal-statuses
                          Force live refresh even for cached terminal tasks.

Environment fallback:
  CRAB_MANIFEST           Default manifest path.
  STATUS_CACHE_DIR        Default status cache directory.
  RECOVERY_CACHE_DIR      Default recovery cache directory.
  STUCK_HOURS             Default stuck-job threshold in hours.
  INCLUDE_REPEATED_FAILURES
                          Default repeated-failure recovery mode.
  FAILED_RETRY_THRESHOLD  Default failed-job retry threshold.
  USE_CACHED_STATUS       Default cache reuse mode (accepted values: 0/1/true/false).

Preconditions:
  - Run 'cmsenv' in this CMSSW work area first.
  - Export X509_USER_PROXY before querying CRAB.

Examples:
  ./prepare_recovery_tasks.sh
  ./prepare_recovery_tasks.sh --use-cached-status --stuck-hours 72
  ./prepare_recovery_tasks.sh --include-repeated-failures --failed-retry-threshold 1

Outputs:
  status_cache/latest_state.json
  recovery_cache/generated_recovery_configs.txt
EOF
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
        --stuck-hours)
            require_option_value "$1" "${2:-}"
            STUCK_HOURS="$2"
            shift 2
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
        *)
            die "Unknown option for ./prepare_recovery_tasks.sh: $1"
            ;;
    esac
done

if [[ "${SHOW_HELP}" == "1" ]]; then
    show_help
    exit 0
fi

USE_CACHED_STATUS="$(resolve_bool "USE_CACHED_STATUS" "${CLI_USE_CACHED_STATUS}" "${USE_CACHED_STATUS:-}" "0")"
INCLUDE_REPEATED_FAILURES="$(resolve_bool "INCLUDE_REPEATED_FAILURES" "${CLI_INCLUDE_REPEATED_FAILURES}" "${INCLUDE_REPEATED_FAILURES:-}" "0")"
STATE_FILE="${STATUS_CACHE_DIR}/latest_state.json"

require_cmssw_env
require_manifest "${MANIFEST}"
require_proxy_env

if [[ "${USE_CACHED_STATUS}" != "1" || ! -f "${STATE_FILE}" ]]; then
    status_args=(
        --manifest "${MANIFEST}"
        --cache-dir "${STATUS_CACHE_DIR}"
    )
    if [[ -n "${CLI_REFRESH_TERMINAL_STATUSES}" ]]; then
        status_args+=(--refresh-terminal-statuses)
    fi
    ./status.sh "${status_args[@]}"
fi

refresh_recovery_args=(
    crab_recovery_task_builder.py
    refresh-recovery
    --state-file "${STATE_FILE}"
    --output-dir "${RECOVERY_CACHE_DIR}"
    --stuck-hours "${STUCK_HOURS}"
    --failed-retry-threshold "${FAILED_RETRY_THRESHOLD}"
)
if [[ "${INCLUDE_REPEATED_FAILURES}" == "1" ]]; then
    refresh_recovery_args+=(--include-repeated-failures)
fi

python3 "${refresh_recovery_args[@]}"

python3 crab_recovery_task_builder.py render-all \
    --state-file "${STATE_FILE}" \
    --skip-unresolved-lumi
