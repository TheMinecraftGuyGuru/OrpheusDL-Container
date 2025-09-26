AI Agents see AGENTS.md
# OrpheusDL-Container

A pre-built container image for running [OrpheusDL](https://github.com/OrfiTeam/OrpheusDL) with the Qobuz provider. The entrypoint keeps the nightly list scheduler running, exposes a lightweight web UI for managing artist/album/track lists, and stages the bundled `settings.json` file into OrpheusDL's config directory so you can mount and customise it directly.

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

1. Create dedicated folders on the host to persist the SQLite database, downloaded music,
   configuration, and modules (for example `./data`, `./music`, `./config`, and `./modules`).
   ```bash
   mkdir -p ./data ./music ./config ./modules
   ```
2. Copy the bundled [`settings.json`](./settings.json) to `./config/settings.json` and edit it
   with your Qobuz credentials plus any other OrpheusDL preferences.
3. Start the service in the background:

   ```bash
   docker compose up -d
   ```

   The compose configuration shown below maps the web UI to port 8080 by default and mounts
   the host directories created in step 1. On the first boot the container will populate the
   mounted `./modules` directory with the bundled providers so you can add or modify modules as
   needed.

## Usage guide

1. Prepare host folders to persist the SQLite database and downloaded music if you have
   not already done so (`./data` and `./music` in the examples below).
2. Edit your mounted `./config/settings.json` to include the required Qobuz credentials under
   `modules.qobuz` and any other preferences you want OrpheusDL to use. Restart the container
   after making changes so the updated file is copied into `/orpheusdl/config/settings.json`.
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
    ports:
      - "8080:8080"
    volumes:
      - ./music:/data/music:rw
      - ./data:/data:rw
      - ./config/settings.json:/app/settings.json:rw
      - ./modules:/orpheusdl/modules:rw
    restart: unless-stopped
```

> **Note:** The compose example above mounts host folders for data, configuration, and modules.
> Adjust the paths and ports to fit your environment before running `docker compose up -d`.

## Environment variables

Editing `settings.json` is the primary way to configure the container, but the entrypoint still
honours the following environment variables when you prefer to manage overrides through your
orchestration tooling.

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

