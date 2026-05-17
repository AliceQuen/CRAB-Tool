#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
source "${SCRIPT_DIR}/crab_common.sh"

show_help() {
    cat <<'EOF'
Usage: ./registerData.sh [generator options]

Generate CRAB configuration files from the local RundataList_*.txt files and
record them in generated_crab_configs.txt.

This is a thin wrapper around ./generate_crab_configs.py. All non-help arguments
are forwarded to the Python generator unchanged.

Preconditions:
  - Run 'cmsenv' in this CMSSW work area first.

Examples:
  ./registerData.sh
  ./registerData.sh --lists RundataList_2025.txt --units-per-job 20
  ./generate_crab_configs.py --help
EOF
}

if (($# > 0)); then
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
    esac
fi

require_cmssw_env

python3 generate_crab_configs.py "$@"
