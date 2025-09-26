#!/bin/bash
set -euo pipefail

SETTINGS_SOURCE="/app/settings.json"
SETTINGS_TARGET="/orpheusdl/config/settings.json"
export SETTINGS_SOURCE SETTINGS_TARGET

web_pid=""
main_child_pid=""

sync_settings_to_source() {
    local source="$SETTINGS_SOURCE"
    local target="$SETTINGS_TARGET"

    if [ ! -f "$target" ]; then
        return 0
    fi

    local source_dir
    source_dir="$(dirname -- "$source")"
    if ! mkdir -p "$source_dir"; then
        echo "[entrypoint] warning: unable to create settings directory: $source_dir" >&2
        return 0
    fi

    local tmp_file
    if ! tmp_file="$(mktemp "$source".XXXXXX)"; then
        echo "[entrypoint] warning: unable to create temporary file for settings sync" >&2
        return 0
    fi

    if ! cp "$target" "$tmp_file" 2>/dev/null; then
        echo "[entrypoint] warning: failed to copy $target to temporary file" >&2
        rm -f "$tmp_file"
        return 0
    fi

    if ! mv "$tmp_file" "$source" 2>/dev/null; then
        echo "[entrypoint] warning: failed to update $source from $target" >&2
        rm -f "$tmp_file"
    fi
}

cleanup() {
    local exit_code=$?

    if [ -n "${web_pid:-}" ]; then
        kill "$web_pid" 2>/dev/null || true
        wait "$web_pid" 2>/dev/null || true
    fi

    if [ -n "${main_child_pid:-}" ]; then
        kill "$main_child_pid" 2>/dev/null || true
        wait "$main_child_pid" 2>/dev/null || true
    fi

    sync_settings_to_source || true

    return "$exit_code"
}

forward_signal() {
    local signal="$1"
    local exit_code=0

    case "$signal" in
        TERM)
            exit_code=143
            ;;
        INT)
            exit_code=130
            ;;
    esac

    if [ -n "${main_child_pid:-}" ]; then
        kill -"$signal" "$main_child_pid" 2>/dev/null || true
    fi

    if [ -n "${web_pid:-}" ]; then
        kill "$web_pid" 2>/dev/null || true
    fi

    exit "$exit_code"
}

trap cleanup EXIT
trap 'forward_signal TERM' TERM
trap 'forward_signal INT' INT

notify_discord() {
    if [ -z "${DISCORD_WEBHOOK_URL:-${DISCORD_WEBHOOK:-}}" ]; then
        return 0
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        return 0
    fi

    local level="${1:-info}"
    local event="${2:-entrypoint_event}"
    local message="${3:-}"
    shift 3 || true

    if [ -z "$message" ]; then
        return 0
    fi

    local args=("--level" "$level" "--event" "$event" "--message" "$message")
    while [ "$#" -gt 0 ]; do
        args+=("--detail" "$1")
        shift
    done

    python3 -m notifications "${args[@]}" >/dev/null 2>&1 || true
}

if [ -n "${LISTS_DB_PATH:-}" ]; then
    lists_db="$LISTS_DB_PATH"
elif [ -n "${LISTS_DB:-}" ]; then
    lists_db="$LISTS_DB"
elif [ -n "${LISTS_DIR:-}" ]; then
    lists_dir="${LISTS_DIR%/}"
    if [ -z "$lists_dir" ]; then
        lists_dir="$LISTS_DIR"
    fi
    lists_db="$lists_dir/orpheusdl-container.db"
else
    lists_db="/data/orpheusdl-container.db"
fi

notify_discord "info" "entrypoint_initialised" "Entrypoint initialised" "db_path=$lists_db"

mkdir -p "$(dirname -- "$lists_db")"

python3 - "$lists_db" <<'PY'
import sqlite3
import sys
from pathlib import Path

db_path = Path(sys.argv[1])
db_path.parent.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(db_path)
conn.execute("PRAGMA foreign_keys = ON")
conn.executescript(
    """
    CREATE TABLE IF NOT EXISTS artists (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_checked_at TEXT
    );

    CREATE TABLE IF NOT EXISTS albums (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        artist TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_checked_at TEXT
    );

    CREATE TABLE IF NOT EXISTS tracks (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        artist TEXT NOT NULL DEFAULT '',
        album TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_checked_at TEXT
    );
    """
)

def ensure_last_checked_column(connection, table_name):
    columns = {row[1] for row in connection.execute(f'PRAGMA table_info({table_name})')}
    if 'last_checked_at' not in columns:
        connection.execute(f'ALTER TABLE {table_name} ADD COLUMN last_checked_at TEXT')

for table_name in ('artists', 'albums', 'tracks'):
    ensure_last_checked_column(conn, table_name)

conn.commit()

conn.close()
PY

fetch_next_queue_entry() {
    python3 - "$lists_db" <<'PY'
import sqlite3
import sys
from pathlib import Path

db_path = Path(sys.argv[1])
if not db_path.exists():
    sys.exit(0)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
try:
    query = """
    SELECT kind, id FROM (
        SELECT 'artist' AS kind, id, last_checked_at, created_at, rowid FROM artists
        UNION ALL
        SELECT 'album' AS kind, id, last_checked_at, created_at, rowid FROM albums
        UNION ALL
        SELECT 'track' AS kind, id, last_checked_at, created_at, rowid FROM tracks
    )
    WHERE id IS NOT NULL
      AND TRIM(id) != ''
      AND SUBSTR(LTRIM(id), 1, 1) != '#'
    ORDER BY (last_checked_at IS NOT NULL), last_checked_at, created_at, rowid
    LIMIT 1
    """
    row = conn.execute(query).fetchone()
finally:
    conn.close()

if row:
    kind = row["kind"] if isinstance(row, sqlite3.Row) else row[0]
    identifier = row["id"] if isinstance(row, sqlite3.Row) else row[1]
    text = str(identifier or "").strip()
    if text:
        print(f"{kind}|{text}")
PY
}

update_last_checked_timestamp() {
    local kind="$1"
    local identifier="$2"

    python3 - "$lists_db" "$kind" "$identifier" <<'PY'
import sqlite3
import sys
from pathlib import Path

db_path = Path(sys.argv[1])
kind = sys.argv[2].strip().lower()
identifier = sys.argv[3].strip()
valid = {"artist", "album", "track"}
if kind not in valid or not identifier:
    sys.exit(0)

table = kind + "s"
conn = sqlite3.connect(db_path)
try:
    conn.execute(
        f"UPDATE {table} SET last_checked_at = CURRENT_TIMESTAMP WHERE id = ?",
        (identifier,),
    )
    conn.commit()
finally:
    conn.close()
PY
}

run_download_job() {
    local kind="$1"
    local identifier="$2"

    echo "[lists] running download for $kind: $identifier"
    local retry_delay="${MUSIXMATCH_CAPTCHA_RETRY_DELAY:-60}"
    if ! [[ "$retry_delay" =~ ^[0-9]+$ ]]; then
        retry_delay=60
    fi
    local captcha_marker="musixmatch --> Captcha error could not be solved"
    local captcha_url="https://apic.musixmatch.com/captcha.html?callback_url=mxm://captcha"

    while true; do
        local tmp_file
        tmp_file="$(mktemp)"
        if python3 -u orpheus.py download qobuz "$kind" "$identifier" 2>&1 | tee "$tmp_file"; then
            notify_discord \
                "success" \
                "scheduler_download_completed" \
                "Scheduler download completed" \
                "kind=$kind" \
                "id=$identifier"
            rm -f "$tmp_file"
            return 0
        fi
        if grep -Fq "$captcha_marker" "$tmp_file"; then
            echo "[lists] musixmatch captcha detected for $kind entry: $identifier" >&2
            echo "[lists] open $captcha_url to solve the captcha; retrying in ${retry_delay}s" >&2
            notify_discord \
                "warning" \
                "musixmatch_captcha" \
                "Musixmatch captcha required" \
                "kind=$kind" \
                "id=$identifier" \
                "retry=${retry_delay}s"
            rm -f "$tmp_file"
            sleep "$retry_delay"
            continue
        fi
        echo "[lists] command failed for $kind entry: $identifier" >&2
        notify_discord \
            "error" \
            "scheduler_download_failed" \
            "Scheduler download failed" \
            "kind=$kind" \
            "id=$identifier"
        rm -f "$tmp_file"
        return 1
    done
}

run_continuous_scheduler() {
    local idle_sleep="${LISTS_SCHEDULER_IDLE_SLEEP:-60}"
    if ! [[ "$idle_sleep" =~ ^[0-9]+$ ]]; then
        idle_sleep=60
    fi
    local between_sleep="${LISTS_SCHEDULER_INTERVAL:-5}"
    if ! [[ "$between_sleep" =~ ^[0-9]+$ ]]; then
        between_sleep=5
    fi

    local idle_logged=0

    while true; do
        local entry
        entry="$(fetch_next_queue_entry)"

        if [ -z "$entry" ]; then
            if [ "$idle_logged" -eq 0 ]; then
                echo "[scheduler] no entries ready; sleeping ${idle_sleep}s"
            fi
            idle_logged=1
            sleep "$idle_sleep"
            continue
        fi

        idle_logged=0

        local kind identifier
        IFS='|' read -r kind identifier <<< "$entry"
        kind="${kind,,}"
        identifier="${identifier#"${identifier%%[![:space:]]*}"}"
        identifier="${identifier%"${identifier##*[![:space:]]}"}"

        if [ -z "$kind" ] || [ -z "$identifier" ]; then
            sleep "$idle_sleep"
            continue
        fi

        if ! run_download_job "$kind" "$identifier"; then
            echo "[scheduler] download failed for $kind entry: $identifier" >&2
        fi

        update_last_checked_timestamp "$kind" "$identifier"

        if [ "$between_sleep" -gt 0 ]; then
            echo "[scheduler] sleeping ${between_sleep}s before next check"
            sleep "$between_sleep"
        fi
    done
}

python3 <<'PY'
import json
import os
from pathlib import Path

settings_path = Path(os.environ['SETTINGS_SOURCE'])
target_path = Path(os.environ['SETTINGS_TARGET'])
QOBUZ_ENV_MAPPING = {
    'app_id': ('QOBUZ_APP_ID', 'APP_ID', 'app_id'),
    'app_secret': ('QOBUZ_APP_SECRET', 'APP_SECRET', 'app_secret'),
    'user_id': ('QOBUZ_USER_ID', 'USER_ID', 'user_id'),
    'token': (
        'QOBUZ_TOKEN',
        'QOBUZ_USER_AUTH_TOKEN',
        'QOBUZ_AUTH_TOKEN',
        'TOKEN',
        'USER_AUTH_TOKEN',
        'user_auth_token',
        'token',
    ),
}
APPLE_USER_TOKEN_ENV_NAMES = (
    'APPLE_MUSIC_USER_TOKEN',
    'APPLE_USER_TOKEN',
    'APPLE_MUSIC_TOKEN',
)
if settings_path.exists():
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        settings = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
        target_path.write_text(settings_path.read_text())
    else:
        modules = settings.setdefault('modules', {})
        qobuz = modules.setdefault('qobuz', {})
        applemusic = modules.setdefault('applemusic', {})


        for key, env_names in QOBUZ_ENV_MAPPING.items():
            for env_name in env_names:
                if env_name in os.environ:
                    value = os.environ[env_name]
                    if qobuz.get(key) != value:
                        qobuz[key] = value
                    break

        user_id = qobuz.get('user_id')
        if user_id is not None and qobuz.get('username') != user_id:
            qobuz['username'] = user_id

        token = qobuz.get('token')
        if token is not None and qobuz.get('password') != token:
            qobuz['password'] = token

        for env_name in APPLE_USER_TOKEN_ENV_NAMES:
            if env_name in os.environ:
                value = os.environ[env_name]
                if applemusic.get('user_token') != value:
                    applemusic['user_token'] = value
                break

        def iter_setting_paths(mapping, parents=None):
            parents = list(parents or [])
            for key, value in mapping.items():
                current_path = parents + [key]
                if isinstance(value, dict):
                    yield from iter_setting_paths(value, current_path)
                else:
                    yield current_path, value

        def env_var_name(path):
            return 'ORPHEUSDL_' + '_'.join(part.upper().replace('-', '_') for part in path)

        def coerce_value(raw, template):
            if isinstance(template, bool):
                normalized = raw.strip().lower()
                if normalized in {'1', 'true', 'yes', 'on'}:
                    return True
                if normalized in {'0', 'false', 'no', 'off'}:
                    return False
                return template
            if isinstance(template, int) and not isinstance(template, bool):
                try:
                    return int(raw.strip())
                except (TypeError, ValueError):
                    return template
            if isinstance(template, float):
                try:
                    return float(raw.strip())
                except (TypeError, ValueError):
                    return template
            return raw

        overrides = []
        for path, value in iter_setting_paths(settings):
            env_name = env_var_name(path)
            if env_name in os.environ:
                overrides.append((path, coerce_value(os.environ[env_name], value)))

        for path, value in overrides:
            node = settings
            for key in path[:-1]:
                node = node.setdefault(key, {})
            node[path[-1]] = value

        target_path.write_text(json.dumps(settings, indent=4) + '\n')
PY

if [ -d /app/modules-default ]; then
    mkdir -p /orpheusdl/modules
    if ! find /orpheusdl/modules -mindepth 1 -maxdepth 1 -print -quit >/dev/null 2>&1; then
        cp -a /app/modules-default/. /orpheusdl/modules/
    fi
fi

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
    notify_discord "info" "scheduler_started" "Continuous scheduler started"
    run_continuous_scheduler
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

set +e
"$@" &
main_child_pid=$!
wait "$main_child_pid"
exit_code=$?
main_child_pid=""
set -e

exit "$exit_code"
