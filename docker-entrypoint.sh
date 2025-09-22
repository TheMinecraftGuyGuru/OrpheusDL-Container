#!/bin/bash
set -euo pipefail

lists_dir="/data/lists"
mkdir -p "$lists_dir"
lists_db="$lists_dir/lists.db"

python3 - "$lists_dir" <<'PY'
import csv
import sqlite3
import sys
from pathlib import Path

lists_dir = Path(sys.argv[1])
db_path = lists_dir / "lists.db"
lists_dir.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(db_path)
conn.execute("PRAGMA foreign_keys = ON")
conn.executescript(
    """
    CREATE TABLE IF NOT EXISTS artists (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS albums (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        artist TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS tracks (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        artist TEXT NOT NULL DEFAULT '',
        album TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """
)
conn.commit()


def migrate_artists_csv(path: Path) -> None:
    if not path.exists():
        return
    migrated = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            artist_id = (row[0] or "").strip()
            if not artist_id or artist_id.startswith("#"):
                continue
            artist_name = (row[1] or "").strip() if len(row) > 1 else artist_id
            conn.execute(
                "INSERT OR IGNORE INTO artists (id, name) VALUES (?, ?)",
                (artist_id, artist_name),
            )
            migrated += 1
    conn.commit()
    if migrated:
        print(f"[lists] migrated legacy artists.csv with {migrated} entries", flush=True)
    try:
        path.unlink()
    except OSError:
        pass


def migrate_artists_txt(path: Path) -> None:
    if not path.exists():
        return
    migrated = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            conn.execute(
                "INSERT OR IGNORE INTO artists (id, name) VALUES (?, ?)",
                (entry, entry),
            )
            migrated += 1
    conn.commit()
    if migrated:
        print(f"[lists] migrated legacy artists.txt with {migrated} entries", flush=True)
    try:
        path.unlink()
    except OSError:
        pass


def migrate_text_list(kind: str) -> None:
    path = lists_dir / f"{kind}s.txt"
    if not path.exists():
        return
    migrated = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            if kind == "album":
                conn.execute(
                    "INSERT OR IGNORE INTO albums (id, title, artist) VALUES (?, ?, ?)",
                    (entry, entry, ""),
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO tracks (id, title, artist, album) VALUES (?, ?, ?, ?)",
                    (entry, entry, "", ""),
                )
            migrated += 1
    conn.commit()
    if migrated:
        print(
            f"[lists] migrated legacy {kind}s.txt with {migrated} entries",
            flush=True,
        )
    try:
        path.unlink()
    except OSError:
        pass


migrate_artists_csv(lists_dir / "artists.csv")
migrate_artists_txt(lists_dir / "artists.txt")
for legacy in ("album", "track"):
    migrate_text_list(legacy)

conn.close()
PY

process_list() {
    local kind="$1"

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
    done < <(python3 - "$lists_db" "$kind" <<'PY'
import sqlite3
import sys
from pathlib import Path

db_path = Path(sys.argv[1])
kind = sys.argv[2]
valid = {"artist", "album", "track"}
if kind not in valid:
    sys.exit(0)

table = kind + "s"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
try:
    query = f"SELECT id FROM {table} ORDER BY created_at, rowid"
    for row in conn.execute(query):
        value = (row["id"] if isinstance(row, sqlite3.Row) else row[0]) or ""
        value = str(value).strip()
        if not value or value.startswith("#"):
            continue
        print(value)
finally:
    conn.close()
PY
    )
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
        process_list "artist"
        for kind in album track; do
            process_list "$kind"
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
