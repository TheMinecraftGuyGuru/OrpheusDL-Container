AI Agents see AGENTS.md
# OrpheusDL-Container

A pre-built container image for running [OrpheusDL](https://github.com/OrfiTeam/OrpheusDL) with the Qobuz provider. The entrypoint keeps the nightly list scheduler running, exposes a lightweight web UI for managing artist/album/track lists, and syncs Qobuz credentials from environment variables into the bundled `settings.json` file at startup.

## Default runtime behaviour

- Starting the image with no explicit command launches two processes:
  - `list_ui_server.py` provides a management UI bound to `$LISTS_WEB_PORT` (default `8080`).
  - A foreground scheduler continuously chooses the queue entry with the oldest `last_checked_at` value (treating new entries as "Never"), runs `download qobuz <type> <id>`, and pauses briefly between attempts or when the queue is empty.
  - The web UI surfaces the last checked timestamp for each list entry so you can confirm what the scheduler processed most recently.
- When you override the service command through Docker Compose (for example `docker compose run orpheusdl download …`), the entrypoint forces Python's unbuffered mode so output is streamed straight into `docker compose logs`.
- Launch an interactive shell for maintenance tasks with `docker compose run --rm --entrypoint /bin/bash orpheusdl`.

### Security notice

The bundled web interface ships with **no authentication and no TLS/SSL support**. Deploy the container behind a reverse proxy (for example, Nginx Proxy Manager, Caddy, or Pangolin) that terminates HTTPS and enforces access control. Exposing the container port directly to the internet is strongly discouraged.

## Quick start

1. Create dedicated folders on the host to persist the SQLite database and downloaded
   music (for example `./data` for database/artwork caches and `./music` for downloads).
2. Copy the provided [`.env.example`](./.env.example) to `.env` and populate it with your
   Qobuz credentials and any optional variables you plan to use. Keep the `.env` file out
   of source control to avoid accidentally committing secrets.
3. Start the service in the background:

   ```bash
   docker compose up -d
   ```

   The compose configuration shown below maps the web UI to port 8080 by default and
   mounts the host directories created in step 1.

## Usage guide

1. Prepare host folders to persist the SQLite database and downloaded music if you have
   not already done so (`./data` and `./music` in the examples below).
2. Populate your `.env` file with the environment variables from the table below. The
   entrypoint copies credentials into `/orpheusdl/config/settings.json` before OrpheusDL
   starts, so the `.env` file is the only place sensitive values need to live.
3. Browse to `http://localhost:8080` (or the host/port you mapped) to open the
   list management UI. Use the artist/album/track search panels to enqueue new
   items. The scheduler will download them automatically using the policy
   described in the previous section.
4. Watch the container logs or configure Discord notifications to monitor
   progress. Manual commands (for example `download qobuz album <id>`) can be
   executed with `docker compose run --rm orpheusdl download qobuz album <id>`.

### Manual command examples

Run a one-off download without the background scheduler:

```bash
docker compose run --rm orpheusdl download qobuz album 90210
```

Start an interactive shell when you need to inspect files inside the
container:

```bash
docker compose run --rm --entrypoint /bin/bash orpheusdl
```

## Example Docker Compose service

```yaml
services:
  orpheusdl:
    image: ghcr.io/theminecraftguyguru/orpheusdl-container:latest
    container_name: orpheusdl
    env_file:
      - ./.env
    environment:
      # Optional runtime tuning (keep secrets in the .env file instead)
      LISTS_WEB_PORT: "8080"
      LISTS_WEB_HOST: 0.0.0.0
      LISTS_WEB_LOG_LEVEL: INFO
    ports:
      - "8080:8080"
    volumes:
      - ./music:/data/music:rw
      - ./data:/data:rw
    restart: unless-stopped
```

> **Note:** The compose example above mounts host folders and references a `.env` file that is not
> committed to source control. Adjust the paths, ports, and optional variables to fit your
> environment before running `docker compose up -d`.

## Environment variables

### Core container variables

| Variable | Required | Description | Aliases / Notes |
| --- | --- | --- | --- |
| `QOBUZ_APP_ID` | Yes | Qobuz application ID used by OrpheusDL. | Also accepts `APP_ID` or lowercase variants. |
| `QOBUZ_APP_SECRET` | Yes | Qobuz application secret. | Also accepts `APP_SECRET` or lowercase variants. |
| `QOBUZ_USER_ID` | Yes | Qobuz user ID; mirrored into the legacy username field. | Also accepts `USER_ID` or lowercase variants. |
| `QOBUZ_TOKEN` | Yes | Qobuz user authentication token; mirrored into the legacy password field. | Also accepts `QOBUZ_USER_AUTH_TOKEN`, `QOBUZ_AUTH_TOKEN`, `TOKEN`, or `USER_AUTH_TOKEN` (case-insensitive). |
| `APPLE_MUSIC_USER_TOKEN` | Yes (for Apple Music features) | Apple Music user token consumed by the bundled Apple Music module. | Also accepts `APPLE_USER_TOKEN` or `APPLE_MUSIC_TOKEN`. |
| `LISTS_WEB_PORT` | No (default `8080`) | Port exposed by `list_ui_server.py`. Update the host mapping in your runtime configuration when you change this value. | |
| `LISTS_WEB_HOST` | No (default `0.0.0.0`) | Interface bound by the web UI. | |
| `LISTS_WEB_LOG_LEVEL` | No (default `INFO`) | Logging level used by the list UI (e.g., `DEBUG`, `INFO`, `WARNING`). | |
| `LISTS_SCHEDULER_INTERVAL` | No (default `5`) | Seconds to wait after finishing an entry before checking the queue again. | |
| `LISTS_SCHEDULER_IDLE_SLEEP` | No (default `60`) | Sleep duration used when no entries are ready to download. | |
| `DISCORD_WEBHOOK_URL` | No | Discord webhook that receives container notifications. | Also accepts `DISCORD_WEBHOOK`. |

Lowercase variants of the Qobuz credential variables are also detected by the entrypoint.


See [`ENVIRONMENT_VARIABLES.md`](./ENVIRONMENT_VARIABLES.md) for an exhaustive list of optional overrides, module-specific settings, and legacy path variables supported by the image.

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

