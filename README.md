# OrpheusDL-Container

## Default runtime behaviour

Running the published image with no explicit command starts the background list UI and
the nightly list scheduler automatically:

```bash
docker run --rm -p 8080:8080 ghcr.io/theminecraftguyguru/orpheusdl-container
```

The UI listens on the port defined by `$LISTS_WEB_PORT` (default `8080`). The entrypoint
keeps the scheduler in the foreground so `docker logs` shows progress from the nightly
loop. To open an interactive shell instead of the scheduler, override the entrypoint:

```bash
docker run --rm -it --entrypoint bash ghcr.io/theminecraftguyguru/orpheusdl-container
```

Any other command supplied to `docker run … <command>` executes through the entrypoint
with stdout forced to unbuffered mode so progress appears in the container logs.

## Runtime configuration

The container entrypoint updates `/app/settings.json` and `/orpheusdl/settings.json` with
credential values from environment variables when the container starts. Set any of the
following variables when running the container to inject the values into the Qobuz module
settings:

- `QOBUZ_APP_ID` or `APP_ID`
- `QOBUZ_APP_SECRET` or `APP_SECRET`
- `QOBUZ_USER_ID` or `USER_ID`
- `QOBUZ_TOKEN`, `QOBUZ_USER_AUTH_TOKEN`, `QOBUZ_AUTH_TOKEN`, `TOKEN`, or `USER_AUTH_TOKEN`

Lowercase variants of these names are also respected. The entrypoint mirrors the user ID
and token values into the legacy username/password fields for compatibility. Values are
only written when the corresponding variable is provided, so existing settings remain
unchanged unless explicitly overridden at runtime.
