#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
source "${SCRIPT_DIR}/crab_common.sh"

MANIFEST="${CRAB_MANIFEST:-generated_crab_configs.txt}"
CLI_DRY_RUN=""
CLI_USE_CACHED_STATUS=""
CLI_REFRESH_TERMINAL_STATUSES=""
STATUS_CACHE_DIR="${STATUS_CACHE_DIR:-status_cache}"
STATE_FILE="${STATUS_CACHE_DIR}/latest_state.json"
SHOW_HELP=0
declare -a FORWARD_ARGS=()

show_help() {
    cat <<'EOF'
Usage: ./resubmit.sh [options] [-- crab resubmit options]

Refresh the cached latest-attempt task status if needed, then resubmit only the
failed CRAB jobs recorded in latest_state.json.

Options:
  -h, --help              Show this help text and exit.
  --manifest PATH         Manifest file to read. Falls back to CRAB_MANIFEST.
  --status-cache-dir PATH Status cache directory. Falls back to STATUS_CACHE_DIR.
  --dry-run               Print crab resubmit commands without executing them.
  --execute               Execute crab resubmit for each failed task.
  --use-cached-status     Reuse the existing status snapshot if it exists.
  --refresh-status        Force a fresh status collection before resubmitting.
  --refresh-terminal-statuses
                          Force live refresh even for cached terminal tasks.
  --                      Stop parsing wrapper options and pass the rest to crab resubmit.

Environment fallback:
  CRAB_MANIFEST           Default manifest path.
  STATUS_CACHE_DIR        Default status cache directory.
  DRY_RUN                 Default dry-run mode (accepted values: 0/1/true/false).
  USE_CACHED_STATUS       Default cache reuse mode (accepted values: 0/1/true/false).

Preconditions:
  - The Python backend enforces 'cmsenv' and X509_USER_PROXY before resubmitting.

Examples:
  ./resubmit.sh
  ./resubmit.sh --execute
  ./resubmit.sh --use-cached-status --execute -- --siteblacklist T2_FOO
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
        --)
            shift
            FORWARD_ARGS=("$@")
            break
            ;;
        *)
            FORWARD_ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ "${SHOW_HELP}" == "1" ]]; then
    show_help
    exit 0
fi

DRY_RUN="$(resolve_bool "DRY_RUN" "${CLI_DRY_RUN}" "${DRY_RUN:-}" "1")"
USE_CACHED_STATUS="$(resolve_bool "USE_CACHED_STATUS" "${CLI_USE_CACHED_STATUS}" "${USE_CACHED_STATUS:-}" "0")"
STATE_FILE="${STATUS_CACHE_DIR}/latest_state.json"
declare -a RESUBMIT_ARGS=(
    --manifest "${MANIFEST}"
    --state-file "${STATE_FILE}"
)

if [[ "${DRY_RUN}" == "1" ]]; then
    RESUBMIT_ARGS+=(--dry-run)
else
    RESUBMIT_ARGS+=(--execute)
fi

if [[ "${USE_CACHED_STATUS}" == "1" ]]; then
    RESUBMIT_ARGS+=(--use-cached-status)
else
    RESUBMIT_ARGS+=(--refresh-status)
fi

if [[ -n "${CLI_REFRESH_TERMINAL_STATUSES}" ]]; then
    RESUBMIT_ARGS+=(--refresh-terminal-statuses)
fi

if ((${#FORWARD_ARGS[@]} > 0)); then
    RESUBMIT_ARGS+=(-- "${FORWARD_ARGS[@]}")
fi

exec python3 crab_resubmit.py "${RESUBMIT_ARGS[@]}"
