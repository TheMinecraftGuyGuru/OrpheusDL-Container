# Repository Guide for Agents

## Maintenance Expectations
- Update this document whenever you learn new information about the repository structure, workflows, conventions, or tooling so future tasks start with an up-to-date brief.
- Expand the sections below as the codebase grows (e.g., when tests, scripts, or additional services are introduced).

## Current Repository Snapshot

### Purpose
- This repository packages the [OrpheusDL](https://github.com/OrfiTeam/OrpheusDL) music downloader and its Qobuz provider module into a container-friendly layout so the tool can be built and run in a consistent environment.

### Layout Highlights
- Root directory contains infrastructure assets only:
  - `Dockerfile`: Alpine-based build that installs system packages, fetches Git submodules, installs Python dependencies from `external/orpheusdl/requirements.txt`, copies the OrpheusDL core and Qobuz module into `/orpheusdl`, and sets a Bash entrypoint with `/orpheusdl` as the working directory.
  - `settings.json`: Default OrpheusDL configuration bundled into the image. It defines download paths/quality, formatting rules, lyrics & cover behaviour, playlist preferences, codec conversion options, and placeholder Qobuz credentials (empty strings by default).
  - `list_ui_server.py`: Lightweight HTTP UI for inspecting and editing the artists/albums/tracks list files; listens on `$LISTS_WEB_PORT` (default `8080`) and serialises file writes with an internal lock.
  - `README.md`: Currently only contains the project title—add setup or usage instructions here if you gather them.
  - `.gitmodules`: Declares the `external/orpheusdl` and `external/orpheusdl-qobuz` submodules; the directories exist but are empty unless initialised.
- `external/`: Hosts the OrpheusDL core and Qobuz provider submodules. Run `git submodule update --init --recursive` after cloning or before building the Docker image so their contents are available.

### Build & Runtime Flow
- Building: `docker build -t orpheusdl .` (ensure submodules are populated first or the copy steps in the Dockerfile will fail).
- Runtime defaults: Without arguments the entrypoint now starts the list UI server (background) and runs the nightly list scheduler in the foreground; the UI is exposed on `$LISTS_WEB_PORT` (default `8080`). Override `CMD` to run custom OrpheusDL commands instead.
- Entrypoint still exports `PYTHONUNBUFFERED=1` and rewrites OrpheusDL commands (e.g. `download`, `search`, `python3 orpheus.py`) so their stdout streams directly into `docker logs` when a command is supplied.
- Configuration: Modify `settings.json` before building or mount an override at runtime to avoid baking credentials into the image.

## Known Gaps / Follow-Ups
- Document any CI, linting, or smoke-test commands once they exist (currently none are defined in the repo).
- Populate README with usage instructions, volume mounting guidance, and example commands when that knowledge becomes available.
- Note additional modules, scripts, or configuration files here as they are introduced

## File Catalog
Use this section to quickly identify where a particular concern lives within the repository. All
paths are relative to the repo root unless stated otherwise.

### Automation & Metadata
- `.github/workflows/docker-publish.yml`: GitHub Actions workflow that builds the container image
  on pushes to `main` (or manual dispatch), authenticates against GHCR, and pushes the image tagged
  as `latest` and with the commit SHA.
- `.gitmodules`: Declares the two Git submodules that hold the OrpheusDL core and the Qobuz
  provider module. You must run `git submodule update --init --recursive` before building so the
  Dockerfile copy steps succeed.

### Documentation & Guidance
- `AGENTS.md`: Living knowledge base for repository conventions. Update this file whenever you
  discover new behaviours or workflows.
- `README.md`: User-facing overview that currently focuses on runtime behaviour, container usage,
  and the environment variables that feed Qobuz credentials into `settings.json` at startup.

### Container Build & Entrypoint
- `Dockerfile`: Alpine-based build. Installs OS dependencies, copies repo contents, initialises
  submodules, installs OrpheusDL Python requirements, then stages OrpheusDL and the Qobuz module
  under `/orpheusdl`. Sets `/usr/local/bin/docker-entrypoint.sh` as the entrypoint and switches the
  working directory to `/orpheusdl` for runtime.
- `docker-entrypoint.sh`: Runtime orchestration script. Ensures list files exist, syncs Qobuz
  credentials from environment variables into `/orpheusdl/config/settings.json`, manages default
  behaviour (starts `list_ui_server.py` and a nightly scheduler when no command is supplied), and
  normalises various OrpheusDL commands to run with unbuffered Python output inside the container.

### Runtime Services & Configuration
- `list_ui_server.py`: Threaded HTTP server for managing the artist/album/track list files. Exposes
  a small HTML interface, serialises file access with locks, streams asynchronous status banners,
  and mirrors the scheduler’s sanitisation so ad-hoc entries behave the same way.
- `settings.json`: Default OrpheusDL configuration baked into the image. Defines download paths,
  quality settings, formatting templates, lyrics/cover behaviour, playlist options, codec
  conversions, and placeholder Qobuz credentials that are overwritten by the entrypoint when
  environment variables are supplied.

### Third-Party Source Mirrors
- `external/orpheusdl`: Git submodule pointing to the upstream OrpheusDL project. Populated during
  builds; contents are copied into `/orpheusdl/`.
- `external/orpheusdl-qobuz`: Git submodule for the Qobuz provider. Copied into
  `/orpheusdl/modules/qobuz/` during the image build.

