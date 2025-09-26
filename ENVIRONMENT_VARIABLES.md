# Extended environment variables

This document lists the advanced and optional environment variables supported by the OrpheusDL container image. Use it alongside the [README](./README.md), which covers the required credentials and primary runtime options.

## OrpheusDL settings overrides

Every leaf value in [`settings.json`](./settings.json) can be overridden via an environment variable. Prefix the JSON path with `ORPHEUSDL_`, join nested keys with underscores, and capitalise the result. For example, `global.general.download_path` becomes `ORPHEUSDL_GLOBAL_GENERAL_DOWNLOAD_PATH`. Boolean values accept `true/false`, `yes/no`, `on/off`, or `1/0`; numeric fields are coerced to integers or floats where appropriate. Undefined or invalid values fall back to the defaults baked into the image.

### `global.general`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_GENERAL_DOWNLOAD_PATH` | `/data/music` | Destination directory for downloaded releases. |
| `ORPHEUSDL_GLOBAL_GENERAL_DOWNLOAD_QUALITY` | `hifi` | Preferred Qobuz quality tier (for example `hifi`, `lossless`, or `hires`). |
| `ORPHEUSDL_GLOBAL_GENERAL_SEARCH_LIMIT` | `10` | Maximum number of results returned by search commands. |

### `global.artist_downloading`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_ARTIST_DOWNLOADING_RETURN_CREDITED_ALBUMS` | `false` | Download albums where the artist is credited but not the main performer. |
| `ORPHEUSDL_GLOBAL_ARTIST_DOWNLOADING_SEPARATE_TRACKS_SKIP_DOWNLOADED` | `true` | Skip already downloaded tracks when using the separate-track workflow. |

### `global.formatting`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_FORMATTING_ALBUM_FORMAT` | `{artist}/{name}{explicit} {quality}` | Directory template for album downloads. |
| `ORPHEUSDL_GLOBAL_FORMATTING_PLAYLIST_FORMAT` | `{name}{explicit}` | Directory template for playlist downloads. |
| `ORPHEUSDL_GLOBAL_FORMATTING_TRACK_FILENAME_FORMAT` | `{track_number}. {name}{explicit} [{sample_rate}kHz {bit_depth}bit]` | Filename template for tracks. |
| `ORPHEUSDL_GLOBAL_FORMATTING_SINGLE_FULL_PATH_FORMAT` | `{artist}/{name}{explicit} [single] [{sample_rate}kHz {bit_depth}bit]/{name}{explicit} [{sample_rate}kHz {bit_depth}bit]` | Directory and filename template for singles. |
| `ORPHEUSDL_GLOBAL_FORMATTING_ENABLE_ZFILL` | `true` | Zero-pad track numbers when formatting filenames. |
| `ORPHEUSDL_GLOBAL_FORMATTING_FORCE_ALBUM_FORMAT` | `false` | Force albums to use the album formatting template regardless of content type. |

### `global.codecs`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_CODECS_PROPRIETARY_CODECS` | `false` | Allow downloads that require proprietary codecs. |
| `ORPHEUSDL_GLOBAL_CODECS_SPATIAL_CODECS` | `true` | Enable spatial audio codec downloads when available. |

### `global.module_defaults`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_MODULE_DEFAULTS_LYRICS` | `default` | Default lyrics provider. |
| `ORPHEUSDL_GLOBAL_MODULE_DEFAULTS_COVERS` | `default` | Default cover art provider. |
| `ORPHEUSDL_GLOBAL_MODULE_DEFAULTS_CREDITS` | `default` | Default credits provider. |

Set any of these variables to `applemusic` if you intend to supply Apple Music credentials and want the bundled module to handle lyrics, artwork, or credits lookups.

### `global.lyrics`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_LYRICS_EMBED_LYRICS` | `true` | Embed plain-text lyrics into downloaded files. |
| `ORPHEUSDL_GLOBAL_LYRICS_EMBED_SYNCED_LYRICS` | `true` | Embed time-synchronised lyrics where available. |
| `ORPHEUSDL_GLOBAL_LYRICS_SAVE_SYNCED_LYRICS` | `true` | Save synchronised lyric files alongside downloads. |

### `global.covers`

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

### `global.playlist`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_GLOBAL_PLAYLIST_SAVE_M3U` | `true` | Export playlists as `.m3u` files. |
| `ORPHEUSDL_GLOBAL_PLAYLIST_PATHS_M3U` | `absolute` | Path style written inside playlist files (`absolute` or `relative`). |
| `ORPHEUSDL_GLOBAL_PLAYLIST_EXTENDED_M3U` | `true` | Include extended metadata lines in playlist exports. |

### `global.advanced`

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

## Module configuration variables

### `modules.applemusic`

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

### `modules.musixmatch`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_MODULES_MUSIXMATCH_TOKEN_LIMIT` | `10` | Maximum retries before rotating Musixmatch tokens. |
| `ORPHEUSDL_MODULES_MUSIXMATCH_LYRICS_FORMAT` | `enhanced` | Preferred Musixmatch lyrics format. |
| `ORPHEUSDL_MODULES_MUSIXMATCH_CUSTOM_TIME_DECIMALS` | `false` | Enable custom decimal precision for lyric timestamps. |

### `modules.qobuz`

| Variable | Default | Description |
| --- | --- | --- |
| `ORPHEUSDL_MODULES_QOBUZ_APP_ID` | *(empty)* | Override for the Qobuz application ID stored in `settings.json`. |
| `ORPHEUSDL_MODULES_QOBUZ_APP_SECRET` | *(empty)* | Override for the Qobuz application secret stored in `settings.json`. |
| `ORPHEUSDL_MODULES_QOBUZ_QUALITY_FORMAT` | `{sample_rate}kHz {bit_depth}bit` | Format string used when labelling Qobuz quality. |
| `ORPHEUSDL_MODULES_QOBUZ_USERNAME` | *(empty)* | Legacy username field kept in sync with `QOBUZ_USER_ID`. |
| `ORPHEUSDL_MODULES_QOBUZ_PASSWORD` | *(empty)* | Legacy password field kept in sync with `QOBUZ_TOKEN`. |

The compatibility aliases (`QOBUZ_APP_ID`, `QOBUZ_TOKEN`, etc.) still populate the same settings. When both a legacy alias and an `ORPHEUSDL_*` variable target the same field, the explicit `ORPHEUSDL_*` override wins.

## Directory paths and volume mounts

The entrypoint writes queue data to `/data/orpheusdl-container.db` by default and expects music under `/data/music`. Override these locations when you want to store data elsewhere:

| Variable | Description |
| --- | --- |
| `LISTS_DB_PATH` | Full path to the SQLite database file inside the container. |
| `LISTS_DB` | Deprecated alias for `LISTS_DB_PATH`. |
| `LISTS_DIR` | Legacy directory variable used to derive `LISTS_DB_PATH`. |
| `MUSIC_DIR` | Directory scanned by the web UI when removing artists or uploading photos. |

Remember to mount the host directories that back these paths (for example, `-v /srv/orpheus/data:/data`). The UI will create missing folders as required but cannot persist data outside mounted volumes.

## Discord notifications

Setting `DISCORD_WEBHOOK_URL` enables rich Discord notifications for noteworthy events:

- Container startup and scheduler lifecycle changes.
- Successful and failed scheduled downloads, including Musixmatch captcha warnings.
- Queue edits (adds/removals) made through the web UI.
- Errors surfaced by background tasks (for example, failed downloads or image fetches).

Notifications include contextual metadata (entry type, identifiers, retry delay, etc.) in the embed fields so you can triage issues quickly without consulting the container logs.
