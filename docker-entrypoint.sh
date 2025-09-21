#!/bin/bash
set -euo pipefail

lists_dir="/data/lists"
mkdir -p "$lists_dir"

for list in artists albums tracks; do
    file="$lists_dir/${list}.txt"
    if [ ! -e "$file" ]; then
        touch "$file"
    fi
done

process_list() {
    local kind="$1"
    local file="$2"

    [ -f "$file" ] || return 0

    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"

        if [ -z "$line" ] || [[ "$line" == \#* ]]; then
            continue
        fi

        echo "[lists] running luckysearch for $kind: $line"
        if ! python3 -u orpheus.py luckysearch qobuz "$kind" "$line"; then
            echo "[lists] command failed for $kind entry: $line" >&2
        fi
    done < "$file"
}

seconds_until_midnight() {
    python3 - <<'PY'
from datetime import datetime, timedelta

now = datetime.now()
target = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
seconds = int((target - now).total_seconds())
print(seconds if seconds > 0 else 0)
PY
}

run_daily_jobs() {
    while true; do
        wait_seconds="$(seconds_until_midnight)"
        if [ -z "$wait_seconds" ] || ! [[ "$wait_seconds" =~ ^[0-9]+$ ]]; then
            wait_seconds=60
        fi
        echo "[scheduler] sleeping $wait_seconds seconds until midnight"
        sleep "$wait_seconds"
        for kind in artist album track; do
            process_list "$kind" "$lists_dir/${kind}s.txt"
        done
    done
}


python3 <<'PY'
import json
import os
from pathlib import Path

settings_path = Path('/app/settings.json')
target_path = Path('/orpheusdl/config/settings.json')
ENV_MAPPING = {
    'app_id': ('QOBUZ_APP_ID', 'APP_ID', 'app_id'),
    'app_secret': ('QOBUZ_APP_SECRET', 'APP_SECRET', 'app_secret'),
    'username': ('QOBUZ_USERNAME', 'USERNAME', 'username'),
    'password': ('QOBUZ_PASSWORD', 'PASSWORD', 'password'),
}

if settings_path.exists():
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        settings = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
        target_path.write_text(settings_path.read_text())
    else:
        modules = settings.setdefault('modules', {})
        qobuz = modules.setdefault('qobuz', {})

        for key, env_names in ENV_MAPPING.items():
            for env_name in env_names:
                if env_name in os.environ:
                    value = os.environ[env_name]
                    if qobuz.get(key) != value:
                        qobuz[key] = value
                    break

        target_path.write_text(json.dumps(settings, indent=4) + '\n')
PY

export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

cmd=("$@")

if [ "${#cmd[@]}" -eq 1 ]; then
    case "${cmd[0]}" in
        bash|sh|/bin/sh)
            cmd=()
            ;;
    esac
fi

if [ "${#cmd[@]}" -eq 0 ]; then
    python3 -u /app/list_ui_server.py &
    web_pid=$!
    trap 'kill "$web_pid" 2>/dev/null || true' EXIT INT TERM
    run_daily_jobs
    exit 0
fi
if [ "${cmd[0]:-}" = "orpheusdl" ]; then
    cmd=("${cmd[@]:1}")
fi

case "${cmd[0]}" in
    orpheus.py|./orpheus.py)
        cmd=(python3 -u "${cmd[@]}")
        ;;
    download|search|luckysearch|settings|sessions)
        cmd=(python3 -u orpheus.py "${cmd[@]}")
        ;;
    -*)
        cmd=(python3 -u orpheus.py "${cmd[@]}")
        ;;
    python*|*/python*)
        python_cmd="${cmd[0]}"
        rest=("${cmd[@]:1}")
        has_unbuffered=0
        for arg in "${cmd[@]}"; do
            if [ "$arg" = "-u" ]; then
                has_unbuffered=1
                break
            fi
        done
        if [ $has_unbuffered -eq 0 ]; then
            cmd=("$python_cmd" -u "${rest[@]}")
        fi
        ;;
esac

set -- "${cmd[@]}"

exec "$@"
