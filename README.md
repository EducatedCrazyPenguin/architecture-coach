# Architecture Coach

Architecture Coach is a private, local dashboard that turns your current project files into an architecture map, a short design review, and lessons grounded in your own source code. It stores every snapshot under `%LOCALAPPDATA%\ArchCoach` and never writes to registered project folders.

## Install and start on Windows

1. Double-click `install.cmd` once. It creates an isolated `.venv`, installs the pinned Python dependencies from `requirements.lock`, and installs the locked browser packages.
2. Architecture Coach automatically discovers the Codex CLI bundled with the Windows Codex app and reuses its saved login. You can instead select an installed Ollama or LM Studio model in **Settings** for local reasoning.
3. Double-click `Start Architecture Coach.cmd`.
4. Add a local project folder in the browser and run its first review. In File Explorer, open the project, click the address bar, and copy a path such as `C:\Users\you\Documents\my-project`. A GitHub URL is not a local folder; clone or download that repository first.

Open **Settings** to change a project's learning goal, review interval, schedule status, or additional excluded paths. Each saved change applies to the next captured review.

You can also use the command line:

```powershell
archcoach doctor
archcoach add "C:\path\to\project" --description "What it does"
archcoach review "project name"
archcoach serve
```

The app binds only to `127.0.0.1:8765`. Use **Exit app** in the sidebar to stop the server and its review worker. Starting it a second time opens the existing server instead of creating another worker.

## What a review contains

- A source-backed summary and main execution path.
- An interactive Archify architecture diagram.
- Stable changes from the last successful review on the same Git branch.
- Up to five practical findings with evidence, impact, a small improvement, and tradeoffs.
- A ten-question repository quiz with four choices, source evidence, saved progress, and an explanation for every selected answer.
- A conversation tied to that immutable review snapshot.

The app uses the saved Codex CLI login and runs review sessions read-only. On Windows it discovers the CLI included with the Codex desktop app even when the launcher has a narrower PATH. Ollama and LM Studio connect directly to their local APIs, independently of Codex CLI. Select either local provider in Settings and choose its installed or loaded model. Reviews and instructor chat use that local model; there is no automatic cloud fallback. If the selected provider is unavailable, the app produces a clearly simpler deterministic review from static analysis. Reviews never run or import target project code.

## Storage and privacy

The SQLite database, content-addressed source blobs, and exported artifacts live in `%LOCALAPPDATA%\ArchCoach`. Sensitive filenames, dependency folders, generated folders, binaries, and links outside the project are excluded. Source snapshots can contain private code, so treat this data directory like the original project.

Archify is vendored at commit `a07fa1d5b2a10cbea110c5a2be2817397a301cdc` under `vendor/archify`; its update checks are disabled. Its MIT licence is retained in that directory.

## Recovery and maintenance

- **Codex login:** Architecture Coach discovers the Windows desktop app's bundled CLI. If its saved session expired, open Codex and sign in, then use **Settings → Refresh diagnostics** before retrying.
- **Ollama:** start the Ollama app, select **Ollama · local**, and refresh diagnostics. The default is `qwen3.6:27b`; install it with `ollama pull qwen3.6:27b` or prepare it with `ollama run qwen3.6:27b`. Enter another installed model name if desired. Codex CLI and account authentication are unnecessary in local mode.
- **LM Studio:** load a downloaded model, open **Developer**, and start the local server (default `127.0.0.1:1234`). Select **LM Studio · local**, refresh diagnostics, and use the model ID shown there. Your downloaded `Qwen3.8-27B-GGUF` is the default setting, but it must be loaded or visible to the server first. Codex CLI and account authentication are unnecessary.
- **Git inspection:** Architecture Coach checks Git ignore rules before capture. It discovers Git from PATH, normal Git for Windows locations, and Codex's bundled runtime. If none is available for a Git repository, install Git for Windows and restart the app.
- **Usage limits and timeouts:** the app pauses scheduled retries after these failures. Retry manually after the limit resets, or adjust the per-call and per-review limits in Settings.
- **Interrupted work:** reopening the launcher marks work abandoned by the prior owning worker and queues one catch-up review when a project is overdue. Completed reviews remain available after a failed attempt.
- **Database migration:** startup applies transactional migrations automatically. Before changing an existing database, it copies the prior file to `%LOCALAPPDATA%\ArchCoach\backups`.
- **Backup:** close the app, then copy the full `%LOCALAPPDATA%\ArchCoach` folder. Restore that folder while the app is stopped.
- **Repair installation:** close the app and run `install.cmd` again. It reuses the checkout and isolated environment and stops with a clear error if Python 3.12, pnpm, Node, Archify, or local assets are unavailable.

## Development

```powershell
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps --no-build-isolation
pnpm install --frozen-lockfile
pytest
archcoach doctor
```

The application is divided into capture, static analysis, Codex, review, diagram, persistence, worker, and web layers. JSON schemas under `src/archcoach/schemas` constrain Codex output.

Product ideas being considered for later releases are tracked in `docs/FUTURE_UPDATES.md`.

The direct local adapters use Ollama's [chat API](https://docs.ollama.com/api/chat), [schema-constrained structured outputs](https://docs.ollama.com/capabilities/structured-outputs), and LM Studio's [OpenAI-compatible local server](https://lmstudio.ai/docs/developer/openai-compat) with [JSON-schema structured output](https://lmstudio.ai/docs/developer/openai-compat/structured-output).
