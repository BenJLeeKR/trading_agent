#!/usr/bin/env bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "ERROR: 이 스크립트는 source로 로드해야 합니다." >&2
  exit 1
fi

AGENT_TRADING_ENV_DIR="${AGENT_TRADING_ENV_DIR:-/etc/agent_trading}"
AGENT_TRADING_REQUIRED_ENV_FILES="${AGENT_TRADING_REQUIRED_ENV_FILES:-runtime.env:ai.env:kis.env}"
AGENT_TRADING_OPTIONAL_ENV_FILES="${AGENT_TRADING_OPTIONAL_ENV_FILES:-local.override.env}"

split_env_file_list() {
  local raw="$1"
  local -n out_ref="$2"
  out_ref=()
  [[ -n "$raw" ]] || return 0
  IFS=':' read -r -a out_ref <<<"$raw"
}

load_external_env_files() {
  local env_dir="$AGENT_TRADING_ENV_DIR"
  local -a required_files optional_files loaded_files missing_files unreadable_files
  local file path joined=""

  split_env_file_list "$AGENT_TRADING_REQUIRED_ENV_FILES" required_files
  split_env_file_list "$AGENT_TRADING_OPTIONAL_ENV_FILES" optional_files

  export AGENT_TRADING_EXTERNAL_ENV_FILE_PATHS=""
  export AGENT_TRADING_EXTERNAL_ENV_LOADED_COUNT="0"

  if [[ ! -d "$env_dir" ]]; then
    return 0
  fi

  if [[ ! -r "$env_dir" || ! -x "$env_dir" ]]; then
    echo "ERROR: 외부 env 디렉터리를 읽을 수 없습니다: $env_dir" >&2
    return 1
  fi

  for file in "${required_files[@]}"; do
    [[ -n "$file" ]] || continue
    path="$env_dir/$file"
    if [[ ! -e "$path" ]]; then
      missing_files+=("$path")
      continue
    fi
    if [[ ! -r "$path" ]]; then
      unreadable_files+=("$path")
      continue
    fi
    loaded_files+=("$path")
  done

  for file in "${optional_files[@]}"; do
    [[ -n "$file" ]] || continue
    path="$env_dir/$file"
    [[ -e "$path" ]] || continue
    if [[ ! -r "$path" ]]; then
      unreadable_files+=("$path")
      continue
    fi
    loaded_files+=("$path")
  done

  if (( ${#missing_files[@]} > 0 )); then
    printf 'ERROR: 필수 외부 env 파일이 없습니다:\n' >&2
    printf -- '- %s\n' "${missing_files[@]}" >&2
    return 1
  fi

  if (( ${#unreadable_files[@]} > 0 )); then
    printf 'ERROR: 외부 env 파일을 읽을 수 없습니다:\n' >&2
    printf -- '- %s\n' "${unreadable_files[@]}" >&2
    return 1
  fi

  if (( ${#loaded_files[@]} == 0 )); then
    return 0
  fi

  set -a
  for path in "${loaded_files[@]}"; do
    # shellcheck disable=SC1090
    source "$path"
  done
  set +a

  for path in "${loaded_files[@]}"; do
    if [[ -z "$joined" ]]; then
      joined="$path"
    else
      joined="$joined:$path"
    fi
  done

  export AGENT_TRADING_EXTERNAL_ENV_FILE_PATHS="$joined"
  export AGENT_TRADING_EXTERNAL_ENV_LOADED_COUNT="${#loaded_files[@]}"
}

load_external_env_files
