AI Agents see AGENTS.md
# OrpheusDL-Container

A pre-built container image for running [OrpheusDL](https://github.com/OrfiTeam/OrpheusDL) with the Qobuz provider. The entrypoint keeps the nightly list scheduler running, exposes a lightweight web UI for managing artist/album/track lists, and syncs Qobuz credentials from environment variables into the bundled `settings.json` file at startup.

## Default runtime behaviour

- Starting the image with no explicit command launches two processes:
  - `list_ui_server.py` provides a management UI bound to `$LISTS_WEB_PORT` (default `8080`).
  - A foreground scheduler continuously chooses the queue entry with the oldest `last_checked_at` value (treating new entries as "Never"), runs `download qobuz <type> <id>`, and pauses briefly between attempts or when the queue is empty.
  - The web UI surfaces the last checked timestamp for each list entry so you can confirm what the scheduler processed most recently.
- Any other command supplied to `docker run … <command>` executes through the entrypoint with Python's unbuffered mode forced so output is streamed straight into `docker logs`.
- Override the entrypoint if you need an interactive shell: `docker run --rm -it --entrypoint bash ghcr.io/theminecraftguyguru/orpheusdl-container`.

### Security notice

The bundled web interface ships with **no authentication and no TLS/SSL support**. Deploy the container behind a reverse proxy (for example, Nginx Proxy Manager, Caddy, or Pangolin) that terminates HTTPS and enforces access control. Exposing the container port directly to the internet is strongly discouraged.

## Quick start

```bash
docker run --rm \
  -p 8080:8080 \
  -v "$(pwd)/music:/data/music" \
  -v "$(pwd)/data:/data" \
  -e QOBUZ_APP_ID=your_app_id \
  -e QOBUZ_APP_SECRET=your_app_secret \
  -e QOBUZ_USER_ID=your_user_id \
  -e QOBUZ_TOKEN=your_user_token \
  -e DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... # optional notifications \
  ghcr.io/theminecraftguyguru/orpheusdl-container:latest
```

## Example Docker Compose service

```yaml
services:
  orpheusdl:
    image: ghcr.io/theminecraftguyguru/orpheusdl-container:latest
    container_name: orpheusdl
    environment:
      # Qobuz credentials (required)
      - QOBUZ_APP_ID=
      - QOBUZ_APP_SECRET=
      - QOBUZ_USER_ID=
      - QOBUZ_TOKEN=
      # Optional runtime tuning
      - LISTS_WEB_PORT=8080          # change to expose the UI on a different port
      - LISTS_WEB_HOST=0.0.0.0       # bind UI to a specific interface
      - LISTS_WEB_LOG_LEVEL=INFO     # adjust UI logging verbosity
    ports:
      - "8080:8080"
    volumes:
      - ./music:/data/music # optional, if not included, music will go into the same folder as data
      - ./data:/data # stores database of artists, albums, and tracks, and cached album covers and artist photos for webUI
    restart: unless-stopped
```

> **Note:** The compose example above is provided for reference only - edit to fit your environment

## Environment variables

| Variable | Required | Description | Aliases / Notes |
| --- | --- | --- | --- |
| `QOBUZ_APP_ID` | Yes | Qobuz application ID used by OrpheusDL. | Also accepts `APP_ID` or lowercase variants. |
| `QOBUZ_APP_SECRET` | Yes | Qobuz application secret. | Also accepts `APP_SECRET` or lowercase variants. |
| `QOBUZ_USER_ID` | Yes | Qobuz user ID; mirrored into the legacy username field. | Also accepts `USER_ID` or lowercase variants. |
| `QOBUZ_TOKEN` | Yes | Qobuz user authentication token; mirrored into the legacy password field. | Also accepts `QOBUZ_USER_AUTH_TOKEN`, `QOBUZ_AUTH_TOKEN`, `TOKEN`, or `USER_AUTH_TOKEN` (case-insensitive). |
| `LISTS_WEB_PORT` | No (default `8080`) | Port exposed by `list_ui_server.py`. Update the host mapping in your runtime configuration when you change this value. | |
| `LISTS_WEB_HOST` | No (default `0.0.0.0`) | Interface bound by the web UI. | |
| `LISTS_WEB_LOG_LEVEL` | No (default `INFO`) | Logging level used by the list UI (e.g., `DEBUG`, `INFO`, `WARNING`). | |
| `LISTS_SCHEDULER_INTERVAL` | No (default `5`) | Seconds to wait after finishing an entry before checking the queue again. | |
| `LISTS_SCHEDULER_IDLE_SLEEP` | No (default `60`) | Sleep duration used when no entries are ready to download. | |
| `DISCORD_WEBHOOK_URL` | No | Discord webhook that receives container notifications. | Also accepts `DISCORD_WEBHOOK`. |

Lowercase variants of the Qobuz credential variables are also detected by the entrypoint.

### Discord notifications

Setting `DISCORD_WEBHOOK_URL` enables rich Discord notifications for noteworthy events:

- Container startup and scheduler lifecycle changes.
- Successful and failed scheduled downloads, including Musixmatch captcha warnings.
- Queue edits (adds/removals) made through the web UI.
- Errors surfaced by background tasks (for example, failed downloads or image fetches).

Notifications include contextual metadata (entry type, identifiers, retry delay, etc.) in the embed fields so you can triage issues quickly without consulting the container logs.

## Data persistence

Mount the following directories to keep your library and queue between container restarts:

- `/data/music` – downloaded releases.
- `/data/orpheusdl-container.db` – SQLite database containing artist/album/track lists.
- `/data/photos` – optional storage for artwork uploaded through the UI.

## Building the image locally

1. Initialise the upstream submodules before building:
   ```bash
   git submodule update --init --recursive
   ```
2. Build the image with Docker:
   ```bash
   docker build -t orpheusdl .
   ```

Once built, the locally tagged image behaves the same as the published `ghcr.io/theminecraftguyguru/orpheusdl-container:latest` image.

