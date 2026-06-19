#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
source "${SCRIPT_DIR}/crab_common.sh"

MANIFEST="${CRAB_MANIFEST:-generated_crab_configs.txt}"
CLI_DRY_RUN=""
SHOW_HELP=0
declare -a FORWARD_ARGS=()

show_help() {
    cat <<'EOF'
Usage: ./kill.sh [options] [-- crab kill options]

Issue "crab kill" for every task listed in the manifest.

Options:
  -h, --help            Show this help text and exit.
  --manifest PATH       Manifest file to read. Falls back to CRAB_MANIFEST.
  --dry-run             Print the crab kill commands without executing them.
  --execute             Execute crab kill for each task in the manifest.
  --                    Stop parsing wrapper options and pass the rest to crab kill.

Environment fallback:
  CRAB_MANIFEST         Default manifest path.
  DRY_RUN               Default dry-run mode (accepted values: 0/1/true/false).

Preconditions:
  - Run 'cmsenv' in this CMSSW work area first.
  - Export X509_USER_PROXY before killing CRAB tasks.

Examples:
  ./kill.sh
  ./kill.sh --execute
  ./kill.sh --execute -- --killwarning
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
        --dry-run)
            CLI_DRY_RUN=1
            shift
            ;;
        --execute)
            CLI_DRY_RUN=0
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

require_cmssw_env
require_manifest "${MANIFEST}"
require_proxy_env

while read -r cfg; do
    [[ -n "${cfg}" ]] || continue
    task_dir="$(cfg_to_task_dir "${cfg}")"
    cmd=(crab kill -d "${task_dir}")
    if ((${#FORWARD_ARGS[@]} > 0)); then
        cmd+=("${FORWARD_ARGS[@]}")
    fi

    if [[ "${DRY_RUN}" == "1" ]]; then
        printf '%q ' "${cmd[@]}"
        printf '\n'
    else
        "${cmd[@]}"
    fi
done < "${MANIFEST}"
