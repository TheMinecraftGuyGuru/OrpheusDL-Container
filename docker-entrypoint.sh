#!/bin/bash
set -euo pipefail

python3 <<'PY'
import json
import os
from pathlib import Path

CONFIG_PATHS = [
    Path("/app/settings.json"),
    Path("/orpheusdl/settings.json"),
]
ENV_MAPPING = {
    "app_id": ("QOBUZ_APP_ID", "APP_ID", "app_id"),
    "app_secret": ("QOBUZ_APP_SECRET", "APP_SECRET", "app_secret"),
    "username": ("QOBUZ_USERNAME", "USERNAME", "username"),
    "password": ("QOBUZ_PASSWORD", "PASSWORD", "password"),
}

for settings_path in CONFIG_PATHS:
    if not settings_path.exists():
        continue
    try:
        settings = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
        continue

    modules = settings.setdefault("modules", {})
    qobuz = modules.setdefault("qobuz", {})
    updated = False

    for key, env_names in ENV_MAPPING.items():
        for env_name in env_names:
            if env_name not in os.environ:
                continue
            value = os.environ[env_name]
            if qobuz.get(key) != value:
                qobuz[key] = value
                updated = True
            break

    if updated:
        settings_path.write_text(json.dumps(settings, indent=4) + "\n")
PY

if [ $# -eq 0 ]; then
    set -- /bin/bash -l
fi

exec "$@"
