# Architecture Coach

Architecture Coach is a private, local dashboard that turns your current project files into an architecture map, a short design review, and lessons grounded in your own source code. It stores every snapshot under `%LOCALAPPDATA%\ArchCoach` and never writes to registered project folders.

## Install and start on Windows

1. Double-click `install.cmd` once.
2. Make sure `codex login status` succeeds in a normal terminal. Run `codex login` if needed.
3. Double-click `Start Architecture Coach.cmd`.
4. Add a local project folder in the browser and run its first review.

Open **Settings** to change a project's learning goal, review interval, schedule status, or additional excluded paths. Each saved change applies to the next captured review.

You can also use the command line:

```powershell
archcoach doctor
archcoach add "C:\path\to\project" --description "What it does"
archcoach review "project name"
archcoach serve
```

The app binds only to `127.0.0.1:8765`. Use **Exit app** in the sidebar to stop the server and its review worker.

## What a review contains

- A source-backed summary and main execution path.
- An interactive Archify architecture diagram.
- Stable changes from the last successful review on the same Git branch.
- Up to five practical findings with evidence, impact, a small improvement, and tradeoffs.
- One to three lessons with a self-check and exercise.
- A conversation tied to that immutable review snapshot.

The app uses the saved Codex CLI login and runs review sessions read-only. If Codex is unavailable, it produces a clearly simpler deterministic review from static analysis so the workflow still completes. Reviews never run or import target project code.

## Storage and privacy

The SQLite database, content-addressed source blobs, and exported artifacts live in `%LOCALAPPDATA%\ArchCoach`. Sensitive filenames, dependency folders, generated folders, binaries, and links outside the project are excluded. Source snapshots can contain private code, so treat this data directory like the original project.

Archify is vendored at commit `a07fa1d5b2a10cbea110c5a2be2817397a301cdc` under `vendor/archify`; its update checks are disabled. Its MIT licence is retained in that directory.

## Development

```powershell
python -m pip install -e ".[dev]"
pnpm install
pytest
archcoach doctor
```

The application is divided into capture, static analysis, Codex, review, diagram, persistence, worker, and web layers. JSON schemas under `src/archcoach/schemas` constrain Codex output.
