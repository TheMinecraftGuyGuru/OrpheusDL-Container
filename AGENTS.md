# Repository Guide for Agents

## Maintenance Expectations
- Update this document whenever you learn new information about the repository structure, workflows, or conventions so future tasks start with an up-to-date brief.
- Keep the information concise but sufficiently detailed to orient new contributors quickly.

## High-Level Overview
- This repository packages the [OrpheusDL](https://github.com/OrfiTeam/OrpheusDL) music downloader and its Qobuz module into a container-friendly layout.
- The root project primarily contains infrastructure files (Docker configuration, default settings, and submodule metadata). All OrpheusDL application code lives inside Git submodules under `external/`.

## Key Files and Directories
- `Dockerfile`: Builds an Alpine-based image, installs Python dependencies, pulls Git submodules, and stages OrpheusDL plus the Qobuz module under `/orpheusdl`. The container entrypoint drops you into Bash inside that directory so the bundled modules are auto-discovered.
- `settings.json`: Default OrpheusDL configuration used inside the container. Adjust this to set download paths, quality targets, metadata formatting, and Qobuz credentials.
- `.gitmodules`: Declares submodules for the upstream OrpheusDL core (`external/orpheusdl`) and the Qobuz provider module (`external/orpheusdl-qobuz`). Run `git submodule update --init --recursive` after cloning to populate them.
- `external/`: Holds the OrpheusDL and Qobuz module submodules once initialised. They are empty until the submodule command above is executed.

## Typical Workflow Notes
- After cloning, initialise submodules before building the Docker image; the Dockerfile expects populated code when it copies `/app/external/...` into the runtime image.
- Build the container with `docker build -t orpheusdl .` (or similar) and run it with your desired command, inheriting the default entrypoint (`/bin/bash -lc`). You can override CMD to run `python3 app.py ...` inside `/orpheusdl` if needed.
- Customise `settings.json` before baking the image or mount an override at runtime to avoid embedding credentials in the image.

## To Do / Knowledge Gaps
- Document any additional modules, scripts, or helper tooling if they are added later.
- Capture testing or validation steps (e.g., linting, unit tests, smoke tests) once the repository contains automation beyond container builds.
