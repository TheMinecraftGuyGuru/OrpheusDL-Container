#!/bin/bash
set -euo pipefail

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
            rm -f "$tmp_file"
            return 0
        fi
        if grep -Fq "$captcha_marker" "$tmp_file"; then
            echo "[lists] musixmatch captcha detected for $kind entry: $identifier" >&2
            echo "[lists] open $captcha_url to solve the captcha; retrying in ${retry_delay}s" >&2
            rm -f "$tmp_file"
            sleep "$retry_delay"
            continue
        fi
        echo "[lists] command failed for $kind entry: $identifier" >&2
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

settings_path = Path('/app/settings.json')
target_path = Path('/orpheusdl/config/settings.json')
ENV_MAPPING = {
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

        user_id = qobuz.get('user_id')
        if user_id is not None and qobuz.get('username') != user_id:
            qobuz['username'] = user_id

        token = qobuz.get('token')
        if token is not None and qobuz.get('password') != token:
            qobuz['password'] = token

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

exec "$@"
