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

### OrpheusDL settings overrides

Every leaf value in [`settings.json`](./settings.json) can be overridden via an environment variable. Prefix the JSON path with `ORPHEUSDL_`, join nested keys with underscores, and capitalise the result. For example, `global.general.download_path` becomes `ORPHEUSDL_GLOBAL_GENERAL_DOWNLOAD_PATH`. Boolean values accept `true/false`, `yes/no`, `on/off`, or `1/0`; numeric fields are coerced to integers or floats where appropriate. Undefined or invalid values fall back to the defaults baked into the image.

#### `global.general`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_GENERAL_DOWNLOAD_PATH` | `/data/music` | Destination directory for downloaded releases. |
| `ORPHEUSDL_GLOBAL_GENERAL_DOWNLOAD_QUALITY` | `hifi` | Preferred Qobuz quality tier (for example `hifi`, `lossless`, or `hires`). |
| `ORPHEUSDL_GLOBAL_GENERAL_SEARCH_LIMIT` | `10` | Maximum number of results returned by search commands. |

#### `global.artist_downloading`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_ARTIST_DOWNLOADING_RETURN_CREDITED_ALBUMS` | `false` | Download albums where the artist is credited but not the main performer. |
| `ORPHEUSDL_GLOBAL_ARTIST_DOWNLOADING_SEPARATE_TRACKS_SKIP_DOWNLOADED` | `true` | Skip already downloaded tracks when using the separate-track workflow. |

#### `global.formatting`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_FORMATTING_ALBUM_FORMAT` | `{artist}/{name}{explicit} {quality}` | Directory template for album downloads. |
| `ORPHEUSDL_GLOBAL_FORMATTING_PLAYLIST_FORMAT` | `{name}{explicit}` | Directory template for playlist downloads. |
| `ORPHEUSDL_GLOBAL_FORMATTING_TRACK_FILENAME_FORMAT` | `{track_number}. {name}{explicit} [{sample_rate}kHz {bit_depth}bit]` | Filename template for tracks. |
| `ORPHEUSDL_GLOBAL_FORMATTING_SINGLE_FULL_PATH_FORMAT` | `{artist}/{name}{explicit} [single] [{sample_rate}kHz {bit_depth}bit]/{name}{explicit} [{sample_rate}kHz {bit_depth}bit]` | Directory and filename template for singles. |
| `ORPHEUSDL_GLOBAL_FORMATTING_ENABLE_ZFILL` | `true` | Zero-pad track numbers when formatting filenames. |
| `ORPHEUSDL_GLOBAL_FORMATTING_FORCE_ALBUM_FORMAT` | `false` | Force albums to use the album formatting template regardless of content type. |

#### `global.codecs`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_CODECS_PROPRIETARY_CODECS` | `false` | Allow downloads that require proprietary codecs. |
| `ORPHEUSDL_GLOBAL_CODECS_SPATIAL_CODECS` | `true` | Enable spatial audio codec downloads when available. |

#### `global.module_defaults`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_MODULE_DEFAULTS_LYRICS` | `applemusic` | Default lyrics provider. |
| `ORPHEUSDL_GLOBAL_MODULE_DEFAULTS_COVERS` | `applemusic` | Default cover art provider. |
| `ORPHEUSDL_GLOBAL_MODULE_DEFAULTS_CREDITS` | `applemusic` | Default credits provider. |

#### `global.lyrics`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_LYRICS_EMBED_LYRICS` | `true` | Embed plain-text lyrics into downloaded files. |
| `ORPHEUSDL_GLOBAL_LYRICS_EMBED_SYNCED_LYRICS` | `true` | Embed time-synchronised lyrics where available. |
| `ORPHEUSDL_GLOBAL_LYRICS_SAVE_SYNCED_LYRICS` | `true` | Save synchronised lyric files alongside downloads. |

#### `global.covers`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_COVERS_EMBED_COVER` | `true` | Embed cover art into downloaded files. |
| `ORPHEUSDL_GLOBAL_COVERS_MAIN_COMPRESSION` | `high` | Compression quality for embedded cover art. |
| `ORPHEUSDL_GLOBAL_COVERS_MAIN_RESOLUTION` | `1400` | Resolution (in pixels) for embedded cover art. |
| `ORPHEUSDL_GLOBAL_COVERS_SAVE_EXTERNAL` | `false` | Save an additional external cover image. |
| `ORPHEUSDL_GLOBAL_COVERS_EXTERNAL_FORMAT` | `png` | File format for external cover images. |
| `ORPHEUSDL_GLOBAL_COVERS_EXTERNAL_COMPRESSION` | `low` | Compression level for external cover images. |
| `ORPHEUSDL_GLOBAL_COVERS_EXTERNAL_RESOLUTION` | `3000` | Resolution (in pixels) for external cover images. |
| `ORPHEUSDL_GLOBAL_COVERS_SAVE_ANIMATED_COVER` | `true` | Preserve animated cover art when the source provides it. |

#### `global.playlist`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_PLAYLIST_SAVE_M3U` | `true` | Export playlists as `.m3u` files. |
| `ORPHEUSDL_GLOBAL_PLAYLIST_PATHS_M3U` | `absolute` | Path style written inside playlist files (`absolute` or `relative`). |
| `ORPHEUSDL_GLOBAL_PLAYLIST_EXTENDED_M3U` | `true` | Include extended metadata lines in playlist exports. |

#### `global.advanced`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_ADVANCED_ADVANCED_LOGIN_SYSTEM` | `false` | Enable the experimental advanced login system. |
| `ORPHEUSDL_GLOBAL_ADVANCED_CODEC_CONVERSIONS_ALAC` | `flac` | Target codec for converting downloaded ALAC files. |
| `ORPHEUSDL_GLOBAL_ADVANCED_CODEC_CONVERSIONS_WAV` | `flac` | Target codec for converting downloaded WAV files. |
| `ORPHEUSDL_GLOBAL_ADVANCED_CONVERSION_FLAGS_FLAC_COMPRESSION_LEVEL` | `5` | Compression level passed to the FLAC encoder. |
| `ORPHEUSDL_GLOBAL_ADVANCED_CONVERSION_KEEP_ORIGINAL` | `false` | Retain source files alongside converted outputs. |
| `ORPHEUSDL_GLOBAL_ADVANCED_COVER_VARIANCE_THRESHOLD` | `8` | Threshold for detecting alternate covers during downloads. |
| `ORPHEUSDL_GLOBAL_ADVANCED_DEBUG_MODE` | `false` | Enable verbose debugging output from OrpheusDL. |
| `ORPHEUSDL_GLOBAL_ADVANCED_DISABLE_SUBSCRIPTION_CHECKS` | `false` | Skip subscription tier validation when authenticating. |
| `ORPHEUSDL_GLOBAL_ADVANCED_ENABLE_UNDESIRABLE_CONVERSIONS` | `false` | Allow conversions normally considered undesirable by OrpheusDL. |
| `ORPHEUSDL_GLOBAL_ADVANCED_IGNORE_EXISTING_FILES` | `false` | Ignore file existence checks and re-download everything. |
| `ORPHEUSDL_GLOBAL_ADVANCED_IGNORE_DIFFERENT_ARTISTS` | `true` | Ignore mismatched artist metadata during downloads. |

#### `modules.applemusic`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_MODULES_APPLEMUSIC_FORCE_REGION` | `us` | Region code forced for Apple Music lookups. |
| `ORPHEUSDL_MODULES_APPLEMUSIC_SELECTED_LANGUAGE` | `en` | Preferred language for Apple Music metadata. |
| `ORPHEUSDL_MODULES_APPLEMUSIC_GET_ORIGINAL_COVER` | `false` | Fetch the original cover image without resizing. |
| `ORPHEUSDL_MODULES_APPLEMUSIC_PRINT_ORIGINAL_COVER_URL` | `false` | Print the original cover art URL to the logs. |
| `ORPHEUSDL_MODULES_APPLEMUSIC_LYRICS_TYPE` | `custom` | Lyrics retrieval mode for Apple Music. |
| `ORPHEUSDL_MODULES_APPLEMUSIC_LYRICS_CUSTOM_MS_SYNC` | `false` | Enable millisecond lyric sync for the custom lyrics mode. |
| `ORPHEUSDL_MODULES_APPLEMUSIC_LYRICS_LANGUAGE_OVERRIDE` | `en` | Override language used for Apple Music lyrics. |
| `ORPHEUSDL_MODULES_APPLEMUSIC_LYRICS_SYLLABLE_SYNC` | `true` | Enable syllable-level lyric syncing. |
| `ORPHEUSDL_MODULES_APPLEMUSIC_USER_TOKEN` | *(empty)* | Explicit Apple Music user token override. |

#### `modules.musixmatch`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_MODULES_MUSIXMATCH_TOKEN_LIMIT` | `10` | Maximum retries before rotating Musixmatch tokens. |
| `ORPHEUSDL_MODULES_MUSIXMATCH_LYRICS_FORMAT` | `enhanced` | Preferred Musixmatch lyrics format. |
| `ORPHEUSDL_MODULES_MUSIXMATCH_CUSTOM_TIME_DECIMALS` | `false` | Enable custom decimal precision for lyric timestamps. |

#### `modules.qobuz`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_MODULES_QOBUZ_APP_ID` | *(empty)* | Override for the Qobuz application ID stored in `settings.json`. |
| `ORPHEUSDL_MODULES_QOBUZ_APP_SECRET` | *(empty)* | Override for the Qobuz application secret stored in `settings.json`. |
| `ORPHEUSDL_MODULES_QOBUZ_QUALITY_FORMAT` | `{sample_rate}kHz {bit_depth}bit` | Format string used when labelling Qobuz quality. |
| `ORPHEUSDL_MODULES_QOBUZ_USERNAME` | *(empty)* | Legacy username field kept in sync with `QOBUZ_USER_ID`. |
| `ORPHEUSDL_MODULES_QOBUZ_PASSWORD` | *(empty)* | Legacy password field kept in sync with `QOBUZ_TOKEN`. |

The compatibility aliases (`QOBUZ_APP_ID`, `QOBUZ_TOKEN`, etc.) still populate the same settings. When both a legacy alias and an `ORPHEUSDL_*` variable target the same field, the explicit `ORPHEUSDL_*` override wins.

### Directory paths and volume mounts

The entrypoint writes queue data to `/data/orpheusdl-container.db` by default
and expects music under `/data/music`. Override these locations when you want to
store data elsewhere:

| Variable | Description |
| --- | --- |
| `LISTS_DB_PATH` | Full path to the SQLite database file inside the container. |
| `LISTS_DB` | Deprecated alias for `LISTS_DB_PATH`. |
| `LISTS_DIR` | Legacy directory variable used to derive `LISTS_DB_PATH`. |
| `MUSIC_DIR` | Directory scanned by the web UI when removing artists or uploading photos. |

Remember to mount the host directories that back these paths (for example,
`-v /srv/orpheus/data:/data`). The UI will create missing folders as required
but cannot persist data outside mounted volumes.

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

