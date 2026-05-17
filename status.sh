#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
source "${SCRIPT_DIR}/crab_common.sh"

MANIFEST="${CRAB_MANIFEST:-generated_crab_configs.txt}"
STATUS_CACHE_DIR="${STATUS_CACHE_DIR:-status_cache}"
STATE_FILE="${STATUS_CACHE_DIR}/latest_state.json"
CLI_RAW_STATUS=""
CLI_REFRESH_TERMINAL_STATUSES=""
CHAIN_SCOPE="latest"
SHOW_HELP=0
declare -a FORWARD_ARGS=()

show_help() {
    cat <<'EOF'
Usage: ./status.sh [options] [-- crab status options]

Query CRAB status for the tasks tracked by the manifest and recovery chains.

By default this wrapper uses crab_status_snapshot.py query-latest to refresh the
cached latest-attempt view under status_cache/latest_state.json. Use
--all-chain-attempts to refresh every tracked attempt in each recovery chain.
Use --raw-status to query CRAB live without updating the cache.

Options:
  -h, --help            Show this help text and exit.
  --manifest PATH       Manifest file to read. Falls back to CRAB_MANIFEST.
  --cache-dir PATH      Status cache directory. Falls back to STATUS_CACHE_DIR.
  --raw-status          Query CRAB live and do not update latest_state.json.
  --cached-status       Force cache-updating mode even if RAW_STATUS is set.
  --all-chain-attempts  Query every tracked attempt in each recovery chain.
  --latest-chain-attempts
                        Query only the latest attempt in each recovery chain.
  --refresh-terminal-statuses
                        Force live refresh even for cached terminal tasks.
  --                    Stop parsing wrapper options and pass the rest through.

Environment fallback:
  CRAB_MANIFEST         Default manifest path.
  STATUS_CACHE_DIR      Default status cache directory.
  RAW_STATUS            Default raw-vs-cached mode (accepted values: 0/1/true/false).

Preconditions:
  - The Python backend enforces 'cmsenv' and X509_USER_PROXY for live queries.

Passthrough:
  - In cache-updating mode, extra arguments are forwarded to crab_status_snapshot.py
    and then to 'crab status --json'.
  - In raw mode, extra arguments are forwarded to 'crab status'.
  - Use '--' to disambiguate wrapper options from passthrough options when needed.

Examples:
  ./status.sh
  ./status.sh --all-chain-attempts
  ./status.sh --cache-dir custom_status_cache
  ./status.sh --raw-status -- --verboseErrors
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
        --cache-dir)
            require_option_value "$1" "${2:-}"
            STATUS_CACHE_DIR="$2"
            shift 2
            ;;
        --raw-status)
            CLI_RAW_STATUS=1
            shift
            ;;
        --cached-status)
            CLI_RAW_STATUS=0
            shift
            ;;
        --all-chain-attempts)
            CHAIN_SCOPE="all"
            shift
            ;;
        --latest-chain-attempts)
            CHAIN_SCOPE="latest"
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

RAW_STATUS="$(resolve_bool "RAW_STATUS" "${CLI_RAW_STATUS}" "${RAW_STATUS:-}" "0")"
STATE_FILE="${STATUS_CACHE_DIR}/latest_state.json"
subcommand="query-latest"
if [[ "${CHAIN_SCOPE}" == "all" ]]; then
    subcommand="query-all"
fi

declare -a SNAPSHOT_ARGS=(
    "${subcommand}"
    --manifest "${MANIFEST}"
    --state-file "${STATE_FILE}"
)

if [[ "${RAW_STATUS}" == "1" ]]; then
    SNAPSHOT_ARGS+=(--no-update-cache --raw-output)
fi

if [[ -n "${CLI_REFRESH_TERMINAL_STATUSES}" ]]; then
    SNAPSHOT_ARGS+=(--refresh-terminal-statuses)
fi

if ((${#FORWARD_ARGS[@]} > 0)); then
    SNAPSHOT_ARGS+=(-- "${FORWARD_ARGS[@]}")
fi

exec python3 crab_status_snapshot.py "${SNAPSHOT_ARGS[@]}"
