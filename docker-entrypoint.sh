#!/bin/bash
set -euo pipefail

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

if [ "${cmd[0]:-}" = "orpheusdl" ]; then
    cmd=("${cmd[@]:1}")
fi

if [ "${#cmd[@]}" -eq 0 ]; then
    cmd=(/bin/bash -l)
else
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
fi

set -- "${cmd[@]}"

exec "$@"
