#!/usr/bin/env bash

die() {
    echo "$*" >&2
    exit 1
}

require_option_value() {
    local option_name="$1"
    local option_value="${2:-}"
    [[ -n "${option_value}" ]] || die "Missing value for ${option_name}."
}

normalize_bool() {
    local label="$1"
    local raw_value="$2"
    local normalized

    normalized="$(printf '%s' "${raw_value}" | tr '[:upper:]' '[:lower:]')"
    case "${normalized}" in
        1|true|yes|on)
            printf '1\n'
            ;;
        0|false|no|off)
            printf '0\n'
            ;;
        "")
            printf '\n'
            ;;
        *)
            die "Invalid boolean value for ${label}: ${raw_value}"
            ;;
    esac
}

resolve_bool() {
    local label="$1"
    local cli_value="$2"
    local env_value="$3"
    local default_value="$4"

    if [[ -n "${cli_value}" ]]; then
        normalize_bool "${label}" "${cli_value}"
        return
    fi

    if [[ -n "${env_value}" ]]; then
        normalize_bool "${label}" "${env_value}"
        return
    fi

    normalize_bool "${label}" "${default_value}"
}

cfg_to_task_dir() {
    local cfg="$1"
    local cfg_basename
    local task_name

    cfg_basename="$(basename "${cfg}")"
    task_name="crab_${cfg_basename%.py}"
    printf '%s\n' "${task_name}"
}

require_cmssw_env() {
    [[ -n "${CMSSW_BASE:-}" ]] || die "CMSSW environment is not active. Run 'cmsenv' first."
    [[ -n "${CMSSW_RELEASE_BASE:-}" ]] || die "CMSSW environment is not active. Run 'cmsenv' first."
    [[ -n "${SCRAM_ARCH:-}" ]] || die "CMSSW environment is not active. Run 'cmsenv' first."
}

require_manifest() {
    local manifest_path="$1"
    if [[ ! -f "${manifest_path}" ]]; then
        die "Missing ${manifest_path}. Run ./registerData.sh first."
    fi
}

require_proxy_env() {
    : "${X509_USER_PROXY:?export X509_USER_PROXY=\$(voms-proxy-info -path) first}"
    if [[ ! -f "${X509_USER_PROXY}" ]]; then
        die "Missing proxy file ${X509_USER_PROXY}."
    fi

    voms-proxy-info -file "${X509_USER_PROXY}" -all >/dev/null
}
