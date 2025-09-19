# OrpheusDL-Container

## Runtime configuration

The container entrypoint updates `/app/settings.json` and `/orpheusdl/settings.json` with
credential values from environment variables when the container starts. Set any of the
following variables when running the container to inject the values into the Qobuz module
settings:

- `QOBUZ_APP_ID` or `APP_ID`
- `QOBUZ_APP_SECRET` or `APP_SECRET`
- `QOBUZ_USERNAME`
- `QOBUZ_PASSWORD`

Lowercase variants of these names are also respected. Values are only written when the
corresponding variable is provided, so existing settings remain unchanged unless explicitly
overridden at runtime.
