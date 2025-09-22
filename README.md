# OrpheusDL-Container

A pre-built container image for running [OrpheusDL](https://github.com/OrfiTeam/OrpheusDL) with the Qobuz provider. The entrypoint keeps the nightly list scheduler running, exposes a lightweight web UI for managing artist/album/track lists, and syncs Qobuz credentials from environment variables into the bundled `settings.json` file at startup.

## Default runtime behaviour

- Starting the image with no explicit command launches two processes:
  - `list_ui_server.py` provides a management UI bound to `$LISTS_WEB_PORT` (default `8080`).
  - A foreground scheduler runs once a day at midnight and executes `luckysearch` downloads for every list entry in `/data/lists/lists.db`.
- Any other command supplied to `docker run … <command>` executes through the entrypoint with Python's unbuffered mode forced so output is streamed straight into `docker logs`.
- Override the entrypoint if you need an interactive shell: `docker run --rm -it --entrypoint bash ghcr.io/theminecraftguyguru/orpheusdl-container`.

### Security notice

The bundled web interface ships with **no authentication and no TLS/SSL support**. Deploy the container behind a reverse proxy (for example, Nginx Proxy Manager, Caddy, or Pangolin) that terminates HTTPS and enforces access control. Exposing the container port directly to the internet is strongly discouraged.

## Quick start

```bash
docker run --rm \
  -p 8080:8080 \
  -v "$(pwd)/music:/data/music" \
  -v "$(pwd)/lists:/data/lists" \
  -e QOBUZ_APP_ID=your_app_id \
  -e QOBUZ_APP_SECRET=your_app_secret \
  -e QOBUZ_USER_ID=your_user_id \
  -e QOBUZ_TOKEN=your_user_token \
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
      - LISTS_DIR=/data/lists        # relocate the lists database
      - MUSIC_DIR=/data/music        # relocate downloaded music
      - LISTS_PHOTO_DIR=/data/photos # enable cover uploads via the UI
      - LISTS_WEB_LOG_LEVEL=INFO     # adjust UI logging verbosity
    ports:
      - "8080:8080"
    volumes:
      - ./music:/data/music
      - ./lists:/data/lists
      # Optional: surface a directory for uploaded photos/covers
      - ./photos:/data/photos
    restart: unless-stopped
```

> **Note:** The compose example above is provided for reference only—do not commit a `docker-compose.yml` file to this repository.

## Environment variables

| Variable | Required | Description | Aliases / Notes |
| --- | --- | --- | --- |
| `QOBUZ_APP_ID` | Yes | Qobuz application ID used by OrpheusDL. | Also accepts `APP_ID` or lowercase variants. |
| `QOBUZ_APP_SECRET` | Yes | Qobuz application secret. | Also accepts `APP_SECRET` or lowercase variants. |
| `QOBUZ_USER_ID` | Yes | Qobuz user ID; mirrored into the legacy username field. | Also accepts `USER_ID` or lowercase variants. |
| `QOBUZ_TOKEN` | Yes | Qobuz user authentication token; mirrored into the legacy password field. | Also accepts `QOBUZ_USER_AUTH_TOKEN`, `QOBUZ_AUTH_TOKEN`, `TOKEN`, or `USER_AUTH_TOKEN` (case-insensitive). |
| `LISTS_WEB_PORT` | No (default `8080`) | Port exposed by `list_ui_server.py`. Update the host mapping in your runtime configuration when you change this value. | |
| `LISTS_WEB_HOST` | No (default `0.0.0.0`) | Interface bound by the web UI. | |
| `LISTS_DIR` | No (default `/data/lists`) | Location of the SQLite database that stores artist/album/track queues. | Ensure the directory is persisted via a volume. |
| `MUSIC_DIR` | No (default `/data/music`) | Destination for downloaded audio files. | Should be a persistent volume. |
| `LISTS_PHOTO_DIR` | No (default `/data/photos`) | Directory where the UI stores uploaded cover images. | Mount a volume if you plan to use artwork uploads. |
| `LISTS_WEB_LOG_LEVEL` | No (default `INFO`) | Logging level used by the list UI (e.g., `DEBUG`, `INFO`, `WARNING`). | |

Lowercase variants of the Qobuz credential variables are also detected by the entrypoint.

## Data persistence

Mount the following directories to keep your library and queue between container restarts:

- `/data/music` – downloaded releases.
- `/data/lists` – SQLite database containing artist/album/track lists. Legacy `.txt` or `artists.csv` data is **not** imported automatically; migrate any historical lists manually before switching.
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

