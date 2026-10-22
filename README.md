# Architecture Coach

Architecture Coach is a private, local dashboard that turns your current project files into an architecture map, a short design review, and lessons grounded in your own source code. It stores every snapshot under `%LOCALAPPDATA%\ArchCoach`. Reviews and chat do not edit registered projects; a separate, explicit approval can save a new OpenSpec planning folder.

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
- A connected learning map with saved import evidence, file-role filters and bounded internal-file views; the original Archify diagram remains an export.
- Stable changes from the last successful review on the same Git branch.
- Up to five practical findings with evidence, impact, a small improvement, and tradeoffs.
- Zero to ten distinct repository questions with saved hints, source evidence, first attempts, retries, a **Not sure** option and offline explanations. Fewer questions means the saved evidence did not support a full set.
- A conversation tied to that immutable review snapshot.
- When a project has standard OpenSpec specifications, a separate requirements view with tentative, cited implementation assessments.

Beside a finding, **Create improvement plan** asks the selected provider for one focused OpenSpec change. Inspect its exact proposal, design, tasks, and specification deltas before using **Approve and save planning files**. Approval creates only a new `openspec/changes/<change-id>/` folder in the registered project after rechecking the saved source and Git context. It never implements, archives, commits, or pushes that project's change. You can download the draft or copy a Codex handoff instead.

The app uses the saved Codex CLI login and runs review sessions read-only. On Windows it discovers the CLI included with the Codex desktop app even when the launcher has a narrower PATH. Ollama and LM Studio connect directly to their local APIs, independently of Codex CLI. Select either local provider in Settings and choose its installed or loaded model. Reviews and instructor chat use that local model; there is no automatic cloud fallback. If the selected provider is unavailable, the app produces a clearly simpler deterministic review from static analysis. Reviews never run or import target project code.

## Learn using a saved review

Choose **Explain this simply** if you are new to reading code. It opens an instructor draft in simpler mode; it does not send a request or replace an unsent question. The guidance starts with the part's job and one input/output example in plain language, defines unfamiliar terms, and asks one short question. Lessons show their explanation before the optional **Show the saved code** disclosure. New reviews use the updated teaching guidance; old saved reviews stay unchanged.

Choose **Start learning this repo** for a resumable short session, or explore freely using **Overview**, **Map**, **Follow a feature**, **Learn**, **Quiz**, and **Changes**. **Ask instructor** stays available in every saved learning view; on a narrow screen it opens a keyboard-accessible drawer. Expand the map to inspect a component’s files and internal imports, or choose a saved source range to prepare a contextual question. Opening a saved view never starts inference.

**Follow a feature** covers supported Python and JavaScript/TypeScript declarations, named arrow functions and directly bound JSX handlers. The selected step highlights its saved excerpt and component. Each outline is a qualified reading sequence, not an observed runtime trace: branches, external calls, ambiguous bindings, missing configuration and unexecuted tests remain labelled. Defaults cap parsing at twenty-four saved files, twelve outlines, thirty steps and depth two; select a saved file to prioritise a narrower view.

Reading outlines preserve supported evaluation order and conditional paths, including linked local functions. Unsupported comprehension/generator ordering is disclosed. Parser updates save a new derived format without overwriting earlier outlines; an instructor selection from an older format asks you to select the step again or clear context while keeping your draft.

Map counts use validated saved import edges, including imports hidden inside component groups. A zero does not prove runtime independence. Detail views cap the drawing at forty files and eighty arrows, disclose omissions and retain full saved per-file counts. Documentation, tests and tooling are separate from application source; uncertain roles remain unknown.

**My learning** keeps first attempts, retries, due recall questions and private notes across repositories. Revision uses saved questions with providers off. Wrong answers return after one day, initial correct answers after three days; delayed correct recall increases the interval up to fourteen days. Same-day retries do not increase recall streaks. A correct answer is practice, not a mastery certificate.

New AI quizzes balance correct answer positions locally while keeping each explanation with its choice. Position-dependent wording such as **all of the above** is rejected through the bounded repair path. Existing saved options and attempts remain unchanged; balanced presentation does not prove an answer is factually correct.

The instructor offers a small hint, simpler/deeper explanation, feedback on your explanation and constrained design practice through the selected provider. Offline reading hints and saved answers require no model. Explain-back requires correct points, missing reasoning and one follow-up question; incomplete output gets one repair, then a visible failed answer. This format does not establish factual correctness. Design practice allows multiple defensible alternatives. Unsent drafts, selected context, question position and the session’s next step are saved locally. Normal navigation and **Exit app** wait for draft saves; browser-close saving is best effort, so a crashed browser or disconnected server can still lose the latest keystrokes. Failures and cancellation keep the draft.

Use **This seems wrong** to record a private correction issue. Flagged questions are paused for future practice while historical attempts remain intact. The instructor’s **Private corrections** panel can mark an issue reviewed; this does not rewrite saved content or establish that it is correct. Generate a new review for corrected teaching material. The glossary connects basic architecture words to separately cited saved examples.

New answers that label a fenced block **Saved code** or **Captured code** must match complete lines in a cited saved range, including Windows line endings. Common indentation can shift for display; truncated lines and empty quotations are rejected. Common formatting does not bypass the narrow source-only claim checks. Invalid output receives at most one repair before a visible failure; these checks do not establish that every explanation is correct.

In a comparison, **Learn from this change** pairs two saved excerpts and asks you to predict possible affected callers. **Compare a concept across saved repos** keeps each origin separate. **Follow this improvement through** records user reports against a later saved review; planning files or observed source edits never prove implementation or passing tests.

**Evidence: 2/3 — current changes have synthetic regression and headless browser evidence. A bounded Bonsai sample correctly explained several saved facts but exposed an inaccurate quiz explanation and omitted follow-up question. The structural feedback fix is tested with synthetic providers; final real teaching, beginner observation and later recall remain open. Installed verification is recorded separately in the relevant change notes.** Implementation checks and pending acceptance are tracked in [the learning roadmap](docs/FUTURE_UPDATES.md). Existing snapshots and artifacts stay unchanged; private learning records use transactional SQLite migrations with pre-migration recovery backups.

## Storage and privacy

The SQLite database, content-addressed source blobs, and exported artifacts live in `%LOCALAPPDATA%\ArchCoach`. Sensitive filenames, dependency folders, generated folders, binaries, and links outside the project are excluded. Source snapshots can contain private code, so treat this data directory like the original project.

Archify is vendored at commit `a07fa1d5b2a10cbea110c5a2be2817397a301cdc` under `vendor/archify`; its update checks are disabled. Its MIT licence is retained in that directory.

## Recovery and maintenance

- **Codex login:** Architecture Coach discovers the Windows desktop app's bundled CLI. If its saved session expired, open Codex and sign in, then use **Settings → Refresh diagnostics** before retrying.
- **Ollama:** start the Ollama app, select **Ollama · local**, and refresh diagnostics. The default is `qwen3.6:27b`; install it with `ollama pull qwen3.6:27b` or prepare it with `ollama run qwen3.6:27b`. Enter another installed model name if desired. Codex CLI and account authentication are unnecessary in local mode.
- **LM Studio:** open **Developer** and start the local server (default `127.0.0.1:1234`). Select **LM Studio · local**, refresh diagnostics, and use the model ID shown there. The detected local Qwen model uses `qwen/qwen3.8-27b`; Architecture Coach loads or reloads it with the 32,768-token context required by its structured reviews. If you prefer the terminal, run `lms server start`. Codex CLI and account authentication are unnecessary.
- **Prism / Bonsai:** run `Install Bonsai Local.cmd` once, then `Start Bonsai Local.cmd`. Select **Prism · Bonsai local** in Settings with model ID `ternary-bonsai-2-27b`. This reuses your downloaded Ternary Bonsai 2 27B PTQ1_0 GGUF from LM Studio's standard model directory. Its special quantisation requires the [author's Prism runtime](https://github.com/PrismML-Eng/Bonsai-demo); a model appearing in LM Studio's list does not prove it can load there. Reviews, repository quizzes, instructor chat and improvement plans use the selected local provider without cloud fallback. See [Bonsai setup](docs/BONSAI.md) for CPU mode, custom paths and shutdown.
- **Git inspection:** Architecture Coach checks Git ignore rules before capture. It discovers Git from PATH, normal Git for Windows locations, and Codex's bundled runtime. If none is available for a Git repository, install Git for Windows and restart the app.
- **Usage limits and timeouts:** the app pauses scheduled retries after these failures. Retry manually after the limit resets, or adjust the per-call and per-review limits in Settings.
- **Interrupted work:** reopening the launcher marks work abandoned by the prior owning worker and queues one catch-up review when a project is overdue. Completed reviews remain available after a failed attempt.
- **Database migration:** startup applies transactional migrations automatically. Before changing an existing database, it writes a consistent SQLite recovery backup, including committed WAL data, to `%LOCALAPPDATA%\ArchCoach\backups`.
- **Backup:** close the app, then copy the full `%LOCALAPPDATA%\ArchCoach` folder. Restore that folder while the app is stopped.
- **Repair installation:** close the app and run `install.cmd` again. It reuses the checkout and isolated environment and stops with a clear error if Python 3.12, pnpm, Node, Archify, or local assets are unavailable.

## Development

```powershell
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps --no-build-isolation
pnpm install --frozen-lockfile
pytest
pnpm spec:check
pnpm spec:progress
archcoach doctor
```

OpenSpec 1.13.2 is pinned in `package.json` and `pnpm-lock.yaml`. New cross-module features and architecture changes use a focused change under `openspec/changes/` with a proposal, specification delta when behavior changes, design, tasks, and verification notes. The generated Codex workflow skills live in `.agents/skills/`; project guidance is in `openspec/config.yaml`. `pnpm spec:check` runs strict validation with telemetry and update checks disabled. `pnpm spec:progress` reports checked task counts, remaining tasks, and recorded blockers. The first-release ledger and audit documents remain dated history.

The application is divided into capture, static analysis, Codex, review, diagram, persistence, worker, and web layers. JSON schemas under `src/archcoach/schemas` constrain Codex output.

Product ideas being considered for later releases are tracked in `docs/FUTURE_UPDATES.md`.

The direct local adapters use Ollama's [chat API](https://docs.ollama.com/api/chat), [schema-constrained structured outputs](https://docs.ollama.com/capabilities/structured-outputs), and LM Studio's [OpenAI-compatible local server](https://lmstudio.ai/docs/developer/openai-compat) with [JSON-schema structured output](https://lmstudio.ai/docs/developer/openai-compat/structured-output).
