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
  - `README.md`: Currently only contains the project title—add setup or usage instructions here if you gather them.
  - `.gitmodules`: Declares the `external/orpheusdl` and `external/orpheusdl-qobuz` submodules; the directories exist but are empty unless initialised.
- `external/`: Hosts the OrpheusDL core and Qobuz provider submodules. Run `git submodule update --init --recursive` after cloning or before building the Docker image so their contents are available.

### Build & Runtime Flow
- Building: `docker build -t orpheusdl .` (ensure submodules are populated first or the copy steps in the Dockerfile will fail).
- Runtime defaults: Container starts in `/orpheusdl` under Bash. Override `CMD` with e.g. `python3 app.py` to launch OrpheusDL directly.
- Configuration: Modify `settings.json` before building or mount an override at runtime to avoid baking credentials into the image. The default download path points to `/mnt/kaina-family/media/music`; adjust to match your environment.

## Known Gaps / Follow-Ups
- Document any CI, linting, or smoke-test commands once they exist (currently none are defined in the repo).
- Populate README with usage instructions, volume mounting guidance, and example commands when that knowledge becomes available.
- Note additional modules, scripts, or configuration files here as they are introduced.
